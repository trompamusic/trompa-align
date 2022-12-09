# set up parameters

args <- commandArgs(trailingOnly=TRUE)
if(length(args) < 3 || length(args) > 4) {
  print("Invoke as: Rscript trompa-align.R $CORRESP_FILE $OUTPUT_FILE $VEROVIO_NOTES_JSON {threshold-in-ms (default=5)}")
  quit()
}

# load libraries

library(tidyverse) # for dplyr, maggritr and friends
library(jsonlite) # for read_json
library(fuzzyjoin) # for difference_inner_join
library(glue) # for interpolated string niceness

correspFile <- args[1] # where our corresp.txt files live
outputFile <- args[2] # where our data files will be generated
verovioNotesJsonFile <- args[3] # Verovio's positions of notes in json format
if(length(args) == 3) {
  threshold <- 5 # alignment threshold between Verovio-timemap and corresp reference times (to overcome rounding issues)
} else {
  threshold <- args[4]
}

generateMapsResultJson <- function(correspFile, attrs, outputFile) { # function to generate a MAPS result object from a corresp file
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
  
  # separate out inserted notes (i.e., performed notes that aren't in the score)
  insertedNotes <- corresp %>% filter(refID == "-1")
  print("Inserted notes detected: ")
  print(nrow(insertedNotes))
  
  # the rest are notes that were aligned via SMAT
  smatAlignedNotes <- setdiff(corresp, insertedNotes)
  
  
  merged <- difference_inner_join(smatAlignedNotes, attrs, by="tstamp",  max_dist = threshold, distance_col = "dist") %>%
    filter(midiPitch == refPitch)
  
  # choose the candidate for each MEI note ID with most similar times
  matched <- group_by(merged, id)  %>% filter(rank(dist, ties.method="first") == 1)
  
  diffs <- setdiff(smatAlignedNotes$refID, matched$refID)
  nonReconciliated<- filter(smatAlignedNotes, refID %in% diffs)

  print(paste(nrow(nonReconciliated), "match failures."))
  
  
  # for MAPS export:
  # group them by their *performance* time
  mapsExport <- matched %>% 
    select(id, alignOntime, alignOnvel) %>% 
    group_by(alignOntime) %>% 
    summarise(list(id), list(alignOnvel))
  head(mapsExport)
  names(mapsExport) <- c("obs_mean_onset", "xml_id", "velocity")
  
  # add in the inserted notes:
  insertedExport <- insertedNotes %>% select(alignOntime, alignSitch, alignOnvel)
  # the inserted note is not in the score and so does not have an MEI (xml) ID
  # use this field instead to store the spelled pitch of the inserted note
  # but because we'll be using it as part of a Linked Data identifier later on in the workflow, replace "#" with "s"
  # (so, e.g., C# becomes Cs)
  insertedExport$alignSitch <- str_replace(paste0("trompa-align_inserted_", insertedExport$alignSitch), "#", "s")
  names(insertedExport) <- c("obs_mean_onset", "xml_id", "velocity")
  mapsExport <- rbind(mapsExport, insertedExport)
  
  mapsExport$confidence <- 0
  mapsExport$obs_num <- as.numeric(rownames(mapsExport))
  mapsExportJson <- toJSON(mapsExport)
  
  write(mapsExportJson, outputFile)
  print(paste("MAPS file written:", outputFile))
}

verovioJsonRaw <- read_file(verovioNotesJsonFile)
attrs <- fromJSON(verovioJsonRaw, simplifyVector = TRUE)

# do the actual work
generateMapsResultJson(correspFile, attrs, outputFile)
