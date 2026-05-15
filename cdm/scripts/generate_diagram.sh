#!/bin/bash
# Generate PNG from Mermaid file using mermaid-cli
# Creates intermediate cdm.mermaid file via python

# Requires: npx -> mermaid-cli, python venv, ubuntu chrome sandbox

../../../../Kabelbaum24/venv/bin/python visualize_schema.py

export CHROME_DEVEL_SANDBOX=/opt/google/chrome/chrome-sandbox

echo "Generating diagram (high resolution)..."
npx -y -p @mermaid-js/mermaid-cli mmdc -i cdm.mermaid -o cdm_schema.png -s 5

if [ $? -eq 0 ]; then
    echo "Success! Diagram saved to cdm_schema.png"
else
    echo "Error generating diagram."
fi
