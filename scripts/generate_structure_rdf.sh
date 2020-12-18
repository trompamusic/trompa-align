#!/usr/bin/bash 
export segmentlineHost=$4
[[ "${segmentlineHost}" != */ ]] && segmentlineHost="${segmentlineHost}/"
[[ "${segmentlineHost}" == */ ]] && segmentlineHost="${segmentlineHost: : -1}"
python scripts/convert_to_rdf.py --format jsonld --meiFile $1 --segmentlineOutput $2 --meiUri $3 --segmentlineUri $segmentlineHost/$2
