library(readr)
library(dplyr)
args <- commandArgs(trailingOnly = TRUE)

if(length(args) != 2) { 
  print("invoke as: Rscript split-performance-offsets-by-work.R /path/to/MidiOffsets-in-Mediafiles-named.tsv /path/to/output-dir")
  quit()
}

MidiOffsets <- read_tsv(args[1]) 
MidiOffsetsByWork <- group_split(MidiOffsets, Work)
MidiOffsetsByWorkKeys <- group_keys(MidiOffsets, Work)

setwd(args[2])

for(i in seq(1, length(MidiOffsetsByWork),1)) { 
  print(paste0(MidiOffsetsByWorkKeys %>% slice(i), '.tsv'))
  write_tsv(MidiOffsetsByWork[[i]], paste0(MidiOffsetsByWorkKeys %>% slice(i), '.tsv'))
}
