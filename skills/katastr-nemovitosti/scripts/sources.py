#!/usr/bin/env python3
"""Read-only Czech cadastral source adapters.

Public endpoints only. Adapted WMS and RUIAN helpers from
https://github.com/dnesdan/pamet-krajiny (MIT). No ownership scraping,
authenticated API, bulk download, or automatic legal inference.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import tempfile
import zlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

from http_client import HttpClient, FetchError, validate_url

RUIAN_URL = "https://ags.cuzk.gov.cz/arcgis/rest/services/RUIAN/MapServer"
PARCEL_WFS_URL = "https://services.cuzk.gov.cz/wfs/inspire-CP-wfs.asp"
CADASTRAL_WMS_URL = "https://services.cuzk.gov.cz/wms/local-km-wms.asp"
LAYERS = {"municipality": 12, "part": 11, "cadastral": 7, "address": 1}
EMPTY_WARNING = "Prázdný výsledek popisuje pouze tento dotaz a rozsah zdroje; není důkazem absence práv ani rizik."

def request_url(base, params):
    """Replace parameters case-insensitively, preserving other public parameters."""
    parts = urlsplit(validate_url(base))
    replaced = {key.lower() for key in params}
    values = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key.lower() not in replaced]
    values.extend(params.items())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(values, doseq=True), ""))


def wms_url(base, params):
    """Drop stale WMS operation parameters; retain provider-specific arguments."""
    parts = urlsplit(validate_url(base))
    controls = {"service", "request", "version", "layers", "styles", "bbox", "srs", "crs", "width", "height", "format", "transparent", "exceptions"}
    values = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key.lower() not in controls]
    clean = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(values), ""))
    return request_url(clean, params)


def provenance(result, url, limitations):
    return {"request_url": url, "response_url": result.url, "retrieved_at": result.retrieved_at,
            "from_cache": result.from_cache, "response_sha256": hashlib.sha256(result.data).hexdigest(),
            "limitations": limitations}


def read_json(client, url, refresh=False):
    result = client.fetch(url, refresh=refresh)
    data = result.json()
    if isinstance(data, dict) and data.get("error"):
        error = data["error"]
        if isinstance(error, dict):
            message = str(error.get("message", error.get("msg", "Provider error")))
            details = error.get("details")
            if details:
                message += "; " + str(details)
        else:
            message = str(error)
        raise FetchError(f"Provider returned an error for {url}: {message}")
    return result, data


def ruian(client, query, kind="address", limit=20, refresh=False):
    if kind not in LAYERS:
        raise ValueError("Unknown RÚIAN kind")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("RÚIAN limit must be 1–50")
    if not isinstance(query, str):
        raise ValueError("RÚIAN query must be text")
    query = query.strip()
    if not 2 <= len(query) <= 200 or re.search(r"[%_*?\x00-\x1f]", query):
        raise ValueError("Use 2–200 characters of a literal name/address, without wildcard or control characters")
    field = "adresa" if kind == "address" else "nazev"
    quoted = query.upper().replace("'", "''")
    params = {"f": "json", "where": f"UPPER({field}) LIKE '%{quoted}%'", "outFields": "*",
              "outSR": "4326", "returnGeometry": "true" if kind in ("part", "address") else "false",
              "returnCentroid": "true" if kind in ("municipality", "cadastral") else "false",
              "orderByFields": field + " ASC,kod ASC", "resultRecordCount": limit + 1}
    url = request_url(f"{RUIAN_URL}/{LAYERS[kind]}/query", params)
    result, data = read_json(client, url, refresh)
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        raise FetchError("Unexpected RÚIAN query response; missing features")
    sr = data.get("spatialReference")
    if sr is not None and (not isinstance(sr, dict) or sr.get("latestWkid", sr.get("wkid")) != 4326):
        raise FetchError("RÚIAN response declares an unexpected spatial reference")
    features = data["features"]
    candidates = []
    for feature in features[:limit]:
        if not isinstance(feature, dict) or not isinstance(feature.get("attributes"), dict):
            raise FetchError("Malformed RÚIAN feature")
        attrs = feature["attributes"]
        candidate = {"code": attrs.get("kod"), "name": attrs.get(field), "kind": kind,
                     "municipality_code": attrs.get("obec"), "district_code": attrs.get("okres"),
                     "attributes": attrs}
        point = feature.get("centroid") if kind in ("municipality", "cadastral") else feature.get("geometry")
        if isinstance(point, dict) and isinstance(point.get("x"), (int, float)) and not isinstance(point.get("x"), bool) and isinstance(point.get("y"), (int, float)) and not isinstance(point.get("y"), bool):
            if not (-180 <= point["x"] <= 180 and -90 <= point["y"] <= 90):
                raise FetchError("RÚIAN returned coordinates outside WGS84 range despite requested outSR=4326")
            candidate["representative_point" if kind in ("municipality", "cadastral") else "registry_point"] = {
                "type": "Point", "coordinates": [point["x"], point["y"]],
                "meaning": "centroid of current administrative geometry, not an exact site" if kind in ("municipality", "cadastral") else "current RÚIAN definition/address point"}
        candidates.append(candidate)
    return {**provenance(result, url, ["Dnešní údaje registru nejsou důkazem historické totožnosti místa, adresy nebo budovy.",
                                       "Kandidáty ověř podle obce, okresu a katastru; žádný se automaticky nevybírá.", EMPTY_WARNING]),
            "query": query, "kind": kind, "candidates": candidates, "selected": None,
            "truncated": bool(data.get("exceededTransferLimit")) or len(features) > limit,
            "returned_count": len(candidates), "total_count": None, "status": "ok" if candidates else "empty"}


def local_name(element):
    return element.tag.rsplit("}", 1)[-1]


def children(element, name):
    return [child for child in element if local_name(child) == name]


def child_text(element, name, default=""):
    found = children(element, name)
    return (found[0].text or "").strip() if found else default


def parse_wms(data):
    if not isinstance(data, bytes) or len(data) > 8_000_000 or b"\x00" in data:
        raise FetchError("WMS XML must be a bounded UTF-8 response")
    if re.search(br"<!ENTITY\s|<!DOCTYPE[^>]*\[", data, re.I):
        raise FetchError("Entity declarations and internal DTD subsets are not accepted in WMS XML")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise FetchError("Response is not valid WMS XML") from exc
    if local_name(root) not in ("WMS_Capabilities", "WMT_MS_Capabilities"):
        messages = [" ".join(node.itertext()).strip() for node in root.iter() if local_name(node) in ("ServiceException", "ExceptionText")]
        raise FetchError("Not a WMS capabilities response" + (": " + "; ".join(messages) if messages else ""))
    version = root.attrib.get("version", "")
    if version not in ("1.1.1", "1.3.0", "1.1.0"):
        raise FetchError(f"Unsupported WMS version {version!r}")
    capabilities = children(root, "Capability")
    if not capabilities:
        raise FetchError("WMS response lacks Capability")
    capability = capabilities[0]
    formats, endpoint = [], None
    requests = children(capability, "Request")
    if requests:
        maps = children(requests[0], "GetMap")
        if maps:
            formats = [(v.text or "").strip() for v in children(maps[0], "Format")]
            for node in maps[0].iter():
                if local_name(node) == "OnlineResource":
                    endpoint = node.attrib.get("{http://www.w3.org/1999/xlink}href") or node.attrib.get("href")
                    if endpoint:
                        break
    layers = []
    def walk(node, inherited_crs, inherited_boxes, inherited_styles, inherited_queryable=False, depth=0):
        if depth > 64:
            raise FetchError("WMS layer tree is unreasonably deep")
        crs = set(inherited_crs)
        for kind in ("CRS", "SRS"):
            for value in children(node, kind):
                crs.update((value.text or "").split())
        boxes = deepcopy_json(inherited_boxes)
        for box in children(node, "BoundingBox"):
            coordinate_system = box.attrib.get("CRS", box.attrib.get("SRS"))
            try:
                bounds = [float(box.attrib[key]) for key in ("minx", "miny", "maxx", "maxy")]
                if coordinate_system and all(math.isfinite(v) for v in bounds):
                    boxes[coordinate_system] = bounds
            except (KeyError, ValueError):
                pass
        styles = dict(inherited_styles)
        for style in children(node, "Style"):
            name = child_text(style, "Name")
            if name:
                styles[name] = child_text(style, "Title", name)
        queryable = node.attrib.get("queryable", "1" if inherited_queryable else "0") == "1"
        name = child_text(node, "Name")
        if name:
            layers.append({"name": name, "title": child_text(node, "Title", name), "abstract": child_text(node, "Abstract"),
                           "crs": sorted(crs), "bounding_boxes_native_axis_order": boxes,
                           "styles": [{"name": k, "title": v} for k, v in styles.items()], "queryable": queryable})
        for child in children(node, "Layer"):
            walk(child, crs, boxes, styles, queryable, depth + 1)
    for layer in children(capability, "Layer"):
        walk(layer, set(), {}, {})
    service = children(root, "Service")
    return {"version": version, "title": child_text(service[0], "Title") if service else "", "get_map_url": endpoint,
            "map_formats": formats, "layers": layers}


def deepcopy_json(value):
    return json.loads(json.dumps(value))


def wms(client, url, version=None, refresh=False):
    params = {"SERVICE": "WMS", "REQUEST": "GetCapabilities"}
    if version:
        params["VERSION"] = version
    url = wms_url(url, params)
    result = client.fetch(url, refresh=refresh)
    return {**provenance(result, url, ["Capabilities popisují službu, nikoli dataci každého snímku nebo historickou přesnost mapy.",
                                      "CRS a styly se dědí z nadřazených vrstev. Nativní BoundingBox používá osy podle uvedené verze WMS."]), **parse_wms(result.data)}


def parse_bbox(value, crs="EPSG:4326"):
    try:
        values = [float(v.strip()) for v in value.split(",")] if isinstance(value, str) else list(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Bbox requires four comma-separated finite numbers") from exc
    if len(values) != 4 or any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in values):
        raise ValueError("Bbox requires four finite numbers")
    a, b, c, d = values
    if a >= c or b >= d:
        raise ValueError("Bbox minimum must be smaller than maximum")
    if crs in ("EPSG:4326", "CRS:84") and not (-180 <= a < c <= 180 and -90 <= b < d <= 90):
        raise ValueError("Longitude/latitude bbox is outside WGS84 bounds")
    return values


def map_parameters(layer, bbox, version, crs, width, height, mime):
    if version not in ("1.1.1", "1.3.0"):
        raise ValueError("Map download supports WMS 1.1.1 or 1.3.0")
    if crs not in ("EPSG:4326", "CRS:84", "EPSG:5514"):
        raise ValueError("Supported CRS: EPSG:4326, CRS:84, EPSG:5514")
    if crs == "EPSG:5514" and version != "1.1.1":
        raise ValueError("EPSG:5514 requires --version 1.1.1 and a native easting/northing bbox in metres; no implicit reprojection")
    if not isinstance(width, int) or isinstance(width, bool) or not isinstance(height, int) or isinstance(height, bool) or not 16 <= width <= 1024 or not 16 <= height <= 1024:
        raise ValueError("Map dimensions must be between 16 and 1024 pixels")
    bbox = parse_bbox(bbox, crs)
    sent = [bbox[1], bbox[0], bbox[3], bbox[2]] if version == "1.3.0" and crs == "EPSG:4326" else bbox
    params = {"SERVICE": "WMS", "VERSION": version, "REQUEST": "GetMap", "LAYERS": layer, "STYLES": "",
              "BBOX": ",".join(format(v, ".12g") for v in sent), "WIDTH": width, "HEIGHT": height, "FORMAT": mime,
              "TRANSPARENT": "FALSE", "CRS" if version == "1.3.0" else "SRS": crs}
    return params


def _png_dimensions(data):
    """Check PNG chunks, CRCs, bounded zlib pixels and scanline filter bytes."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise FetchError("WMS response is not PNG")
    position, header, idats, palette, ended_idat, ended = 8, None, [], False, False, False
    while position < len(data):
        if position + 12 > len(data):
            raise FetchError("Truncated PNG chunk")
        length = struct.unpack(">I", data[position:position + 4])[0]
        kind = data[position + 4:position + 8]
        end = position + 12 + length
        if end > len(data) or not kind.isalpha() or not 65 <= kind[2] <= 90:
            raise FetchError("Invalid PNG chunk structure")
        body = data[position + 8:position + 8 + length]
        crc = struct.unpack(">I", data[position + 8 + length:end])[0]
        if zlib.crc32(kind + body) & 0xffffffff != crc:
            raise FetchError("PNG chunk CRC mismatch")
        if header is None and kind != b"IHDR":
            raise FetchError("PNG must begin with IHDR")
        if kind == b"IHDR":
            if header is not None or length != 13:
                raise FetchError("Invalid or repeated PNG header")
            header = struct.unpack(">IIBBBBB", body)
            width, height, depth, color, compression, filtering, interlace = header
            depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
            if not (1 <= width <= 1024 and 1 <= height <= 1024) or depth not in depths.get(color, set()) or compression != 0 or filtering != 0 or interlace not in (0, 1):
                raise FetchError("Unsupported PNG dimensions or encoding")
        elif kind == b"PLTE":
            if palette or idats or not length or length % 3 or length > 768 or header[3] in (0, 4):
                raise FetchError("Invalid PNG palette")
            if header[3] == 3 and length // 3 > 2 ** header[2]:
                raise FetchError("PNG palette exceeds indexed bit depth")
            palette = True
        elif kind == b"IDAT":
            if ended_idat or (header[3] == 3 and not palette):
                raise FetchError("Invalid PNG pixel-chunk order or missing palette")
            idats.append(body)
        elif kind == b"IEND":
            if length or not idats or end != len(data):
                raise FetchError("Invalid PNG end or missing pixel data")
            ended = True
        elif kind in (b"acTL", b"fcTL", b"fdAT") or kind[:1].isupper():
            raise FetchError("Animated PNG or unknown critical chunk is unsupported")
        if idats and kind != b"IDAT":
            ended_idat = True
        position = end
    if header is None or not ended:
        raise FetchError("Incomplete PNG")
    width, height, depth, color, _, _, interlace = header
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    passes = [(0, 0, 1, 1)] if not interlace else [(0,0,8,8),(4,0,8,8),(0,4,4,8),(2,0,4,4),(0,2,2,4),(1,0,2,2),(0,1,1,2)]
    rows = []
    for x, y, dx, dy in passes:
        pw, ph = max(0, (width - x + dx - 1) // dx), max(0, (height - y + dy - 1) // dy)
        if pw and ph:
            rows.extend([(pw * channels * depth + 7) // 8] * ph)
    expected = sum(n + 1 for n in rows)
    try:
        inflater = zlib.decompressobj()
        pixels = inflater.decompress(b"".join(idats), expected + 1)
    except zlib.error as exc:
        raise FetchError("Invalid PNG zlib pixel stream") from exc
    if len(pixels) != expected or not inflater.eof or inflater.unconsumed_tail or inflater.unused_data:
        raise FetchError("PNG pixel stream is incomplete or exceeds declared dimensions")
    offset = 0
    for row_size in rows:
        if pixels[offset] > 4:
            raise FetchError("Unknown PNG scanline filter")
        offset += row_size + 1
    return width, height


def image_dimensions(data, mime):
    if mime == "image/png":
        return _png_dimensions(data)
    if mime == "image/jpeg":
        # JPEG marker/size validation is intentionally not an entropy decoder.
        # Export metadata labels this lesser validation level explicitly.
        if len(data) < 4 or not data.startswith(b"\xff\xd8\xff") or not data.endswith(b"\xff\xd9"):
            raise FetchError("WMS response lacks JPEG framing")
        pos, dimensions = 2, None
        while pos + 4 <= len(data):
            if data[pos] != 255:
                break
            while pos < len(data) and data[pos] == 255:
                pos += 1
            if pos >= len(data):
                break
            marker = data[pos]; pos += 1
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                break
            if pos + 2 > len(data):
                break
            length = struct.unpack(">H", data[pos:pos + 2])[0]
            if length < 2 or pos + length > len(data):
                break
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                if length < 8 or length != 8 + 3 * data[pos + 7]:
                    break
                height, width = struct.unpack(">HH", data[pos + 3:pos + 7])
                if not (1 <= width <= 1024 and 1 <= height <= 1024):
                    break
                dimensions = (width, height)
            if marker == 0xDA:
                if dimensions is None or length < 6 or length != 6 + 2 * data[pos + 2] or pos + length >= len(data) - 2:
                    break
                return dimensions
            pos += length
        raise FetchError("JPEG frame/scan headers or dimensions could not be checked")
    raise FetchError("WMS map response must have image/png or image/jpeg MIME type")


def _publish_exclusive(files):
    """Stage all bytes, then publish with atomic no-replace filesystem links.

    There is no portable two-path transaction. If publication of a later path
    fails, roll back only paths which still refer to our own staged inode. Never
    replace a file or symlink created by another writer during network work.
    """
    staged, published = [], []
    try:
        for destination, data in files:
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=destination.name + ".", suffix=".tmp", dir=destination.parent)
            staged.append((Path(temporary), destination))
            with os.fdopen(fd, "wb") as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
        for temporary, destination in staged:
            os.link(temporary, destination)
            published.append((temporary, destination))
    except BaseException:
        for temporary, destination in reversed(published):
            try:
                original = temporary.stat()
                current = destination.lstat()
                if (original.st_dev, original.st_ino) == (current.st_dev, current.st_ino):
                    destination.unlink()
            except FileNotFoundError:
                pass
        raise
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def wms_map(client, url, layer, bbox, out, width=800, height=600, version=None, crs="EPSG:4326", refresh=False):
    path = Path(out)
    extension = path.suffix.lower()
    if extension not in (".png", ".jpg", ".jpeg"):
        raise ValueError("Map output filename must end in .png, .jpg or .jpeg")
    sidecar = Path(str(path) + ".json")
    if path.exists() or sidecar.exists():
        raise ValueError("Map or sidecar already exists; choose new output paths")
    mime = "image/png" if extension == ".png" else "image/jpeg"
    # Validate coordinate interpretation and dimensions before any network call.
    map_parameters(layer, bbox, version or "1.3.0", crs, width, height, mime)
    caps = wms(client, url, version, refresh)
    negotiated = caps["version"]
    if version and negotiated != version:
        raise FetchError(f"WMS did not negotiate requested version {version}; got {negotiated}")
    matches = [record for record in caps["layers"] if record["name"] == layer]
    if len(matches) != 1:
        raise ValueError("Select an exact, unique layer name from the wms command")
    if crs not in matches[0]["crs"]:
        raise ValueError(f"Layer does not advertise {crs}; available: {', '.join(matches[0]['crs'])}. No coordinates were reprojected.")
    if mime not in caps["map_formats"]:
        raise ValueError(f"WMS does not advertise requested image format {mime}")
    endpoint = caps.get("get_map_url") or url
    # Some older official capabilities advertise HTTP. Upgrade only the same
    # hostname; never follow a provider-supplied cross-origin or credential URL.
    ep, original = urlsplit(endpoint), urlsplit(validate_url(url))
    if ep.hostname != original.hostname:
        raise FetchError("Advertised GetMap uses another host; inspect and supply its canonical service URL explicitly")
    if original.scheme == "https" and ep.scheme == "http":
        endpoint = urlunsplit(("https", ep.netloc, ep.path, ep.query, ""))
    validate_url(endpoint)
    params = map_parameters(layer, bbox, negotiated, crs, width, height, mime)
    map_url = wms_url(endpoint, params)
    result = client.fetch(map_url, refresh=refresh)
    actual_mime = result.content_type.split(";", 1)[0].strip().lower()
    if actual_mime != mime:
        raise FetchError(f"WMS returned {actual_mime}, expected {mime}; image was not saved")
    dimensions = image_dimensions(result.data, actual_mime)
    if dimensions != (width, height):
        raise FetchError(f"WMS returned dimensions {dimensions}, expected {(width, height)}")
    metadata = {**provenance(result, map_url, ["Jde o vyžádaný mapový výřez. Mapový obraz neprokazuje vlastnictví, právo přístupu ani stavební možnost.",
                                             "Ověř licenci vrstvy, datum měření/snímku a vhodnost měřítka; neuvedené datum nedoplňuj odhadem.",
                                             "Příkaz neprovádí reprojekci. EPSG:5514 používá nativní metry a jen WMS 1.1.1."]),
                "capabilities": {key: caps[key] for key in ("request_url", "retrieved_at", "from_cache")},
                "layer": layer, "layer_title": matches[0]["title"], "version": negotiated, "crs": crs,
                "bbox_input": parse_bbox(bbox, crs), "bbox_input_order": "easting,northing" if crs == "EPSG:5514" else "longitude,latitude",
                "bbox_request": params["BBOX"], "width": width, "height": height, "mime": actual_mime,
                "sha256": hashlib.sha256(result.data).hexdigest(), "bytes": len(result.data), "file": str(path), "sidecar": str(sidecar),
                "image_validation": "png_chunks_crc_and_pixel_stream" if mime == "image/png" else "jpeg_headers_and_dimensions_only"}
    if mime == "image/jpeg":
        metadata["limitations"].append("JPEG byl zkontrolován podle hlaviček, markerů a rozměrů; obrazová data musí ověřit dekodér nebo vizuální kontrola.")
    _publish_exclusive([
        (path, result.data),
        (sidecar, (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8")),
    ])
    return metadata




def _positive_id(value, name, width=15):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0," + str(width - 1) + r"}", value):
        raise ValueError(f"{name} must be a positive numeric identifier written as text")
    return value


def _validate_geojson_geometry(geometry):
    """Validate the WGS84 structures returned by the official GeoJSON endpoint."""
    if geometry is None:
        return None
    if not isinstance(geometry, dict) or geometry.get("type") not in ("Polygon", "MultiPolygon"):
        raise FetchError("Expected a Polygon or MultiPolygon from RÚIAN")
    polygons = [geometry.get("coordinates")] if geometry["type"] == "Polygon" else geometry.get("coordinates")
    if not isinstance(polygons, list) or not polygons or len(polygons) > 1000:
        raise FetchError("Malformed or excessive polygon collection")
    count = 0
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise FetchError("Empty polygon")
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                raise FetchError("Polygon ring is not closed")
            for pair in ring:
                count += 1
                if count > 100000:
                    raise FetchError("Geometry exceeds coordinate limit")
                if not isinstance(pair, list) or len(pair) != 2 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in pair):
                    raise FetchError("Malformed coordinate")
                if not (-180 <= pair[0] <= 180 and -90 <= pair[1] <= 90):
                    raise FetchError("Coordinate outside WGS84 bounds")
    return {"type": geometry["type"], "coordinates": polygons[0] if geometry["type"] == "Polygon" else polygons}


def ruian_building(client, code, refresh=False):
    """Get one identified RÚIAN building; never infer ownership from its attributes."""
    code = _positive_id(code, "RÚIAN building code")
    url = request_url(f"{RUIAN_URL}/3/query", {
        "f": "geojson", "where": f"kod = {code}", "outFields": "*", "outSR": "4326",
        "returnGeometry": "true", "resultRecordCount": 2,
    })
    result, data = read_json(client, url, refresh)
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        raise FetchError("RÚIAN building response is not a GeoJSON FeatureCollection")
    if data.get("crs"):
        crs = data["crs"].get("properties", {}).get("name", "") if isinstance(data["crs"], dict) else ""
        if crs not in ("urn:ogc:def:crs:OGC:1.3:CRS84", "urn:ogc:def:crs:OGC::CRS84", "EPSG:4326"):
            raise FetchError("RÚIAN building response declares an unexpected CRS")
    records = []
    for feature in data["features"][:2]:
        if not isinstance(feature, dict) or not isinstance(feature.get("properties"), dict):
            raise FetchError("Malformed building feature")
        props = feature["properties"]
        if str(props.get("kod")) != code:
            raise FetchError("RÚIAN returned a different building identifier")
        records.append({"code": code, "attributes": props, "geometry": _validate_geojson_geometry(feature.get("geometry"))})
    return {**provenance(result, url, ["Údaje stavebního objektu nejsou listem vlastnictví ani dokladem povolení stavby.",
             "Geometrie a atributy vyžadují kontrolu aktuálnosti a vazby na konkrétní jednotku či parcelu."]),
            "status": "ok" if records else "empty", "records": records, "selected": None,
            "truncated": bool(data.get("exceededTransferLimit")) or len(data["features"]) > 2}


def _safe_xml(data):
    if not isinstance(data, bytes) or len(data) > 8_000_000:
        raise FetchError("XML exceeds the supported size")
    # Do not permit UTF-16 tricks around the entity check; service XML is UTF-8.
    if b"\x00" in data or re.search(br"<!DOCTYPE|<!ENTITY", data, re.I):
        raise FetchError("DTD/entity declarations and non-UTF-8 XML are not supported")
    try:
        return ET.fromstring(data)
    except (ET.ParseError, UnicodeError, RecursionError) as exc:
        raise FetchError("Response is not valid service XML") from exc


def _first_text(node, name):
    for child in node.iter():
        if local_name(child) == name and child.text:
            return child.text.strip()
    return ""


def _geometry_from_gml(feature):
    """Parse explicit WGS84/CRS84 polygon rings, keeping holes and all patches.

    No reprojection or heuristic axis guessing. Unsupported geometry remains an
    explicit unresolved item rather than a wrong polygon.
    """
    container = next((n for n in feature if local_name(n) == "geometry"), None)
    if container is None:
        return None, "Služba neuvedla polygonovou geometrii."
    # Every member has to be accounted for. Silently taking the recognizable
    # polygons from a mixed/linked MultiSurface would hide missing areas.
    allowed = {"geometry", "MultiSurface", "surfaceMember", "surfaceMembers",
               "MultiPolygon", "polygonMember", "polygonMembers", "Surface",
               "patches", "Polygon", "PolygonPatch", "exterior", "interior",
               "LinearRing", "posList", "pos"}
    for node in container.iter():
        if node.attrib.get("{http://www.w3.org/1999/xlink}href") is not None:
            return None, "Geometrie obsahuje odkazovaný člen; bez jeho rozlišení není polygon úplný."
        if node is not container and (not node.tag.startswith("{http://www.opengis.net/gml/3.2}") or local_name(node) not in allowed):
            return None, "Geometrie obsahuje nepodporovaný člen; žádná neúplná část se nevydává za celý polygon."
        kind = local_name(node)
        if kind in {"surfaceMember", "polygonMember"} and len(node) != 1:
            return None, "Geometrie obsahuje prázdný nebo nejednoznačný člen."
        if kind in {"MultiSurface", "surfaceMembers", "MultiPolygon", "polygonMembers", "Surface", "patches"} and not len(node):
            return None, "Geometrie obsahuje prázdnou kolekci nebo plochu."
    parent = {child: node for node in container.iter() for child in node}
    def attr(node, name):
        while node is not None:
            if name in node.attrib:
                return node.attrib[name]
            node = parent.get(node)
        return None
    polygons = []
    for polygon in container.iter():
        if local_name(polygon) not in ("Polygon", "PolygonPatch"):
            continue
        rings = []
        boundaries = [n for n in polygon if local_name(n) == "exterior"] + [n for n in polygon if local_name(n) == "interior"]
        if not boundaries or local_name(boundaries[0]) != "exterior":
            return None, "Polygon nemá rozpoznaný vnější prstenec."
        for boundary in boundaries:
            ring = next((n for n in boundary if local_name(n) == "LinearRing"), None)
            if ring is None:
                return None, "Geometrie obsahuje nepodporovaný křivkový prstenec; je nutné GIS zpracování."
            pos_lists = [n for n in ring if local_name(n) == "posList"]
            points = [n for n in ring if local_name(n) == "pos"]
            if len(pos_lists) > 1 or (pos_lists and points) or not (pos_lists or points):
                return None, "Souřadnicová posloupnost není jednoznačná."
            coordinate_nodes = pos_lists or points
            values = []
            for node in coordinate_nodes:
                dimension = attr(node, "srsDimension") or "2"
                if dimension != "2":
                    return None, "Podporována je pouze dvourozměrná geometrie."
                crs = attr(node, "srsName") or ""
                if crs in ("http://www.opengis.net/def/crs/EPSG/0/4326", "urn:ogc:def:crs:EPSG::4326", "EPSG:4326"):
                    swap = True
                elif crs in ("urn:ogc:def:crs:OGC:1.3:CRS84", "http://www.opengis.net/def/crs/OGC/1.3/CRS84", "CRS:84"):
                    swap = False
                else:
                    return None, "Neznámý nebo nepodporovaný souřadnicový systém; žádná automatická reprojekce."
                try:
                    numbers = [float(v) for v in (node.text or "").split()]
                except ValueError as exc:
                    raise FetchError("Invalid GML coordinate") from exc
                if len(numbers) % 2 or (points and len(numbers) != 2) or len(numbers) > 200000:
                    raise FetchError("Invalid or excessive GML coordinate sequence")
                for i in range(0, len(numbers), 2):
                    pair = [numbers[i + 1], numbers[i]] if swap else numbers[i:i + 2]
                    if not all(math.isfinite(x) for x in pair) or not (-180 <= pair[0] <= 180 and -90 <= pair[1] <= 90):
                        raise FetchError("Invalid WGS84 coordinate in GML")
                    values.append(pair)
            if len(values) < 4 or values[0] != values[-1]:
                raise FetchError("GML polygon ring is not closed")
            rings.append(values)
        polygons.append(rings)
    if not polygons:
        return None, "Geometrie není rozpoznaný Polygon nebo PolygonPatch."
    result = {"type": "Polygon", "coordinates": polygons[0]} if len(polygons) == 1 else {"type": "MultiPolygon", "coordinates": polygons}
    return _validate_geojson_geometry(result), ""


def parse_wfs_parcels(data, max_features=2):
    if not isinstance(max_features, int) or isinstance(max_features, bool) or not 1 <= max_features <= 50:
        raise ValueError("WFS parsing limit must be 1–50")
    root = _safe_xml(data)
    if local_name(root) in ("ExceptionReport", "ServiceExceptionReport"):
        messages = [" ".join(n.itertext()).strip() for n in root.iter() if local_name(n) in ("ExceptionText", "ServiceException")]
        raise FetchError("WFS error: " + "; ".join(messages)[:500])
    if root.tag != "{http://www.opengis.net/wfs/2.0}FeatureCollection":
        raise FetchError("Response is not a WFS 2.0 FeatureCollection")
    features = []
    for member in root:
        if local_name(member) != "member":
            continue
        nodes = list(member)
        if len(nodes) != 1 or nodes[0].tag not in ("{http://inspire.ec.europa.eu/schemas/cp/4.0}CadastralParcel", "{http://inspire.ec.europa.eu/schemas/cp/3.0}CadastralParcel"):
            raise FetchError("Unexpected WFS feature type")
        features.append(nodes[0])
    try:
        matched = root.attrib.get("numberMatched", "unknown")
        matched = int(matched) if matched != "unknown" else None
        returned = int(root.attrib["numberReturned"])
    except (ValueError, KeyError) as exc:
        raise FetchError("WFS response lacks valid result counts") from exc
    if returned < 0 or (matched is not None and (matched < returned or matched < 0)) or returned != len(features):
        raise FetchError("WFS result count is inconsistent with its features")
    records = []
    for feature in features[:max_features]:
        fid = feature.attrib.get("{http://www.opengis.net/gml/3.2}id", "")
        if not fid:
            raise FetchError("Cadastral feature has no gml:id")
        geometry, warning = _geometry_from_gml(feature)
        area = _first_text(feature, "areaValue")
        area_node = next((n for n in feature.iter() if local_name(n) == "areaValue"), None)
        records.append({"registry_id": fid, "label": _first_text(feature, "label"),
                        "national_cadastral_reference": _first_text(feature, "nationalCadastralReference"),
                        "area_value": area, "area_unit": area_node.attrib.get("uom", "") if area_node is not None else "",
                        "begin_lifespan_version": _first_text(feature, "beginLifespanVersion"),
                        "geometry": geometry, "geometry_warning": warning})
    return {"records": records, "returned_count": len(records), "total_count": matched,
            "truncated": len(features) > max_features or (matched is not None and matched > len(records)),
            "response_timestamp": root.attrib.get("timeStamp"), "status": "ok" if records else "empty", "selected": None}


def parcel(client, cadastral_code, number, series="land", refresh=False):
    """Retrieve a bounded exact natural-identity WFS query, including geometry."""
    if not isinstance(cadastral_code, str) or not re.fullmatch(r"[0-9]{6}", cadastral_code):
        raise ValueError("Use the six-digit official cadastral-area code")
    if not isinstance(number, str) or not re.fullmatch(r"[1-9][0-9]{0,7}(?:/[1-9][0-9]{0,4})?", number):
        raise ValueError("Use an exact parcel number, e.g. 99 or 99/3; select the numeric series separately")
    if series not in ("land", "building"):
        raise ValueError("Parcel series must be land or building")
    text = ("st. " if series == "building" else "") + number
    url = request_url(PARCEL_WFS_URL, {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
        "STOREDQUERY_ID": "GetParcel", "UPPER_ZONING_ID": cadastral_code, "TEXT": text,
        "SRSNAME": "http://www.opengis.net/def/crs/EPSG/0/4326", "COUNT": 2})
    result = client.fetch(url, refresh=refresh)
    parsed = parse_wfs_parcels(result.data, max_features=2)
    expected_label = re.sub(r"\s+", "", text)
    expected_reference = cadastral_code + "-" + expected_label
    for record in parsed["records"]:
        if re.sub(r"\s+", "", record["label"]) != expected_label or re.sub(r"\s+", "", record["national_cadastral_reference"]) != expected_reference:
            raise FetchError("WFS response does not match the requested cadastral area, parcel number and numeric series")
    return {**provenance(result, url, ["WFS poskytuje identitu a geometrii parcely, nikoli vlastníky, právní omezení ani stavební přípustnost.",
             "Souřadnice jsou převedeny pouze změnou pořadí os deklarovaného WGS84 do GeoJSON longitude,latitude; neprobíhá reprojekce.",
             "Přesnost hranice závisí na podkladu mapy. Nenalezená geometrie neznamená neexistenci parcely.", EMPTY_WARNING]),
            "cadastral_code": cadastral_code, "number": number, "series": series, **parsed}
