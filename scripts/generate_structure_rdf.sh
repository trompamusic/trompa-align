#!/usr/bin/bash 
python scripts/convert_to_rdf.py --format jsonld --meiFile $1 --segmentlineOutput $2 --meiUri $3 --segmentlineUri $4
