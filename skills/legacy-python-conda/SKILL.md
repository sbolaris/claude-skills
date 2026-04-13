---
name: legacy-python-conda
description: Python 2.7 conda environment setup, pymongo/GridFS extraction, and py2/3 compatibility patterns
tags: [python, conda, legacy, pymongo, gridfs]
---

# Skill: Legacy Python (2.7) Extraction Scripts with Conda

**When to use:** Working with an older Python 2.7 codebase (e.g., Django 1.x, pymongo 2/3) and needing to write a standalone extraction or utility script that connects to the same infrastructure without pulling in the full Django stack.

---

## Pattern: conda environment for isolated legacy deps

```bash
# Create the env with Python 2.7 and needed packages
conda create -n my_extract_env python=2.7 pymongo -y

# Verify imports work
conda run -n my_extract_env python -c "import pymongo, gridfs; print(pymongo.version)"

# Run the script
conda run -n my_extract_env python extract_script.py [args]
```

Use `conda run -n <env>` rather than activating — more portable in scripts and CI.

---

## Script shebang

Point directly at the conda env's python so the script is self-contained:

```python
#!/home/ubuntu/miniconda3/envs/my_extract_env/bin/python
# -*- coding: utf-8 -*-
from __future__ import print_function, division, unicode_literals, absolute_import
```

The `from __future__` imports make Python 2 behave closer to Python 3.

---

## Python 2/3 compatibility notes

| Python 3 pattern | Python 2 compatible replacement |
|---|---|
| `print(x)` | `print(x)` (ok with `from __future__ import print_function`) |
| `f"text {var}"` | `'text {var}'.format(var=var)` |
| `os.makedirs(path, exist_ok=True)` | manual `if not os.path.exists(path): os.makedirs(path)` |
| `open(..., encoding='utf-8')` | omit encoding arg in py2 |
| `super()` | `super(ClassName, self)` |

---

## pymongo 2.x / 3.x authentication

pymongo < 4 uses `db.authenticate()` (removed in 4.x):

```python
client = pymongo.MongoClient(host)
db = client[db_name]
db.authenticate(user, pwd)   # pymongo 2.x / 3.x only
```

If upgrading to pymongo 4+ (Python 3), pass credentials in URI:

```python
client = pymongo.MongoClient(host, username=user, password=pwd, authSource=db_name)
db = client[db_name]
```

---

## GridFS file download pattern (pymongo 3.x)

```python
import gridfs

fs = gridfs.GridFS(db)

# Get file metadata
file_doc = db.fs.files.find_one({'_id': file_id})
filename = file_doc['filename']
upload_date = file_doc['uploadDate']   # naive UTC datetime

# Stream to disk
gout = fs.get(file_id)
with open(dest_path, 'wb') as fh:
    while True:
        chunk = gout.readchunk()
        if not chunk:
            break
        fh.write(chunk)
```

---

## Organizing output by upload date

```python
date_str  = file_doc['uploadDate'].strftime('%Y-%m-%d')   # naive UTC
dest_path = os.path.join(output_root, date_str, filename)
```

---

## argparse skeleton (Python 2/3 compatible)

```python
import argparse

parser = argparse.ArgumentParser(description='Extract files from MongoDB.')
parser.add_argument('--host',    default='my.mongo.host')
parser.add_argument('--out',     default=os.path.expanduser('~/output'))
parser.add_argument('--after',   default=None, help='YYYY-MM-DD')
parser.add_argument('--before',  default=None, help='YYYY-MM-DD')
parser.add_argument('--force',   action='store_true')
parser.add_argument('--dry-run', action='store_true', dest='dry_run')
args = parser.parse_args()
```
