#!/bin/bash
# Double-click this file to launch Majic Movie Selector

cd "$(dirname "$0")"
source .venv/bin/activate
python desktop_app.py
