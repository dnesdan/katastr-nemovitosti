#!/usr/bin/env python3
"""Verify the distributable skill, local links, examples and schema offline."""
from pathlib import Path
import importlib.util
import json
import re
import sys

import yaml
from jsonschema import Draft202012Validator

ROOT=Path(__file__).resolve().parents[1]
SKILL=ROOT/'skills/katastr-nemovitosti'
sys.path.insert(0,str(SKILL/'scripts'))
from case_model import require_valid,public_case

text=(SKILL/'SKILL.md').read_text(encoding='utf-8')
assert text.startswith('---\n'), 'Missing frontmatter'
metadata=yaml.safe_load(text.split('---',2)[1])
assert set(metadata)=={'name','description'} and metadata['name']=='katastr-nemovitosti'
assert isinstance(metadata['description'],str) and metadata['description'].strip()
assert len(text.splitlines())<500
assert '[TODO' not in text
ui=yaml.safe_load((SKILL/'agents/openai.yaml').read_text(encoding='utf-8'))['interface']
assert 25<=len(ui['short_description'])<=64
assert '$katastr-nemovitosti' in ui['default_prompt']
schema=json.loads((SKILL/'schema.json').read_text(encoding='utf-8'))
Draft202012Validator.check_schema(schema)
validator=Draft202012Validator(schema)
cases=[]
for path in [SKILL/'assets/template.json',*sorted((ROOT/'examples').glob('*.json'))]:
 data=json.loads(path.read_text(encoding='utf-8'))
 if data.get('schema_version')!='property-case/1.0':continue
 require_valid(data);validator.validate(data);cases.append(path.name)
 if data['case']['sharing']=='public-reviewed':
  validator.validate(public_case(data))
for path in ROOT.rglob('*.md'):
 if any(p in {'.git','__pycache__','.venv'} for p in path.parts):continue
 content=path.read_text(encoding='utf-8')
 for dest in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)',content):
  dest=dest.split(' "',1)[0]
  if dest.startswith('<') and dest.endswith('>'):dest=dest[1:-1]
  if dest.startswith(('http:','https:','mailto:','#')):continue
  target=(path.parent/dest.split('#',1)[0]).resolve()
  assert target.exists(),f'Broken local link in {path}: {dest}'
cat=json.loads((SKILL/'references/source-catalogue.json').read_text(encoding='utf-8'))
assert len({x['id'] for x in cat['sources']})==len(cat['sources'])
assert all(x['implementation'] in {'adapter','manual','user_document'} for x in cat['sources'])
for generated in (ROOT/'examples').glob('*.html'):
 s=generated.read_text(encoding='utf-8')
 assert '<html lang="cs">' in s
 assert 'Content-Security-Policy' in s
 assert not re.search(r'<(?:script|link|img)[^>]+(?:src|href)=["\']https?://',s,re.I)
 assert 'inspection_version' not in s
for path in ROOT.rglob('*'):
 if path.is_file() and '.git' not in path.parts:
  assert not path.name.endswith(('.pem','.key')),f'Credential-like file: {path}'
print(f'OK: metadata, {len(cases)} cases, JSON Schema, local links, {len(cat["sources"])} sources, offline exports')
