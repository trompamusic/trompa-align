# set up parameters

args <- commandArgs(trailingOnly=TRUE)
if(length(args) < 3 || length(args) > 4) {
  print("Invoke as: Rscript trompa-align.R /path/to/corresp/dir /path/to/output/dir /path/to/MEI-file.mei {threshold-in-ms (default=5)}")
  quit()
}

# load libraries

library(tidyverse) # for dplyr, maggritr and friends
library(jsonlite) # for read_json
library(fuzzyjoin) # for difference_inner_join
library(reticulate) # to execute the Verovio python code
library(glue) # for interpolated string niceness


correspDir <- args[1] # where our corresp.txt files live
outputDir <- args[2] # where our data files will be generated
meiFile <- args[3] # which MEI file we're aligning with
if(length(args) == 3) { 
  threshold <- 5 # alignment threshold between Verovio-timemap and corresp reference times (to overcome rounding issues)
} else { 
  threshold <- args[4]
}

generateMapsResultJson <- function(correspFile, correspDir, outputDir) { # function to generate a MAPS result object from a corresp file
  correspFile <- paste0(correspDir, "/", correspFile)
  print(paste("Processing", correspFile))
  correspRaw <- read_file(correspFile)
  correspString <- str_replace_all(correspRaw, "\\*", "-1")
  corresp <- read_tsv(correspString, 
                      skip=1,
                      col_names = c("alignID", "alignOntime", "alignSitch", 
                                    "alignPitch", "alignOnvel", "refID", "refOntime", 
                                    "refSitch", "refPitch", "refOnvel", "ignoreMe")
  )
  
  # drop last column of corresp (artifact of bad TSV formatting)
  corresp <- select(corresp, -one_of("ignoreMe"))
  corresp <- mutate(corresp, tstamp = refOntime * 1000)
  print("Merging")
  
  merged <- difference_inner_join(corresp, attrs, by="tstamp",  max_dist = threshold, distance_col = "dist") %>%
    filter(midiPitch == refPitch)
  
  # choose the candidate for each MEI note ID with most similar times
  matched <- group_by(merged, id)  %>% filter(rank(dist, ties.method="first") == 1)
  head(matched)
  
  diffs <- setdiff(corresp$refID, matched$refID)
  onlycorresp <- filter(corresp, refID %in% diffs)

  print(paste(nrow(onlycorresp), "match failures:"))
  #print(onlycorresp)
  
  
  # for MAPS export:
  # group them by their *performance* time
  mapsExport <- matched %>% 
    select(id, alignOntime, alignOnvel) %>% 
    group_by(alignOntime) %>% 
    summarise(list(id), list(alignOnvel))
  head(mapsExport)
  names(mapsExport) <- c("obs_mean_onset", "xml_id", "velocity")
  mapsExport$confidence <- 0
  mapsExport$obs_num <- as.numeric(rownames(mapsExport))
  mapsExportJson <- toJSON(mapsExport)
  
  write(mapsExportJson, paste0(outputDir, "/", basename(correspFile), ".maps.json"))
  print(paste("File written:", paste0(outputDir, "/", basename(correspFile), ".maps.json")))
}

# Python code to grab MIDI values from Verovio, in order to align corresp file with MEI note IDs
generateAttrsPython <- glue("
import verovio
import json

tk = verovio.toolkit()
try: 
    tk.loadFile('{meiFile}')
except:
    print('Python: Could not load MEI file: {meiFile}')

print('Python: Rendering to MIDI')
tk.renderToMIDI() # must render to MIDI first or getMIDIValuesForElement won't work
print('Python: Rendering to Timemap')
timemap = json.loads(tk.renderToTimemap())
allNotes = []
timemapNoteOns = list(filter(lambda x: 'on' in x, timemap))
list(map(lambda x: list(map(lambda y: allNotes.append({{
    'id': y,
    'tstamp': x['tstamp'],
    'midiPitch': json.loads(tk.getMIDIValuesForElement(y))['pitch']
    }}), x['on'])), timemapNoteOns))
allNotesJson = json.dumps(allNotes)
print('Python: Done...')
")

attrsJson <- py_run_string(generateAttrsPython)$allNotesJson
attrs <- parse_json(attrsJson, simplifyVector = TRUE)

correspFiles <- dir(correspDir, pattern="corresp.txt$")
print("Corresp files:")
print(correspFiles)

# do the actual work
for(f in 1:length(correspFiles)) { 
  generateMapsResultJson(correspFiles[f], correspDir, outputDir)
}
