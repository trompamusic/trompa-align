#use ubuntu as base
FROM ubuntu:latest

#install dependencies (R, python, wget, unzip)
RUN apt-get update
RUN apt-get -y install tzdata
RUN apt-get -y install wget && apt-get -y install git && apt-get install -y unzip && apt-get install -y make && apt-get install -y r-base && apt-get install python3.7
RUN apt-get -y install python3-pip

#download smat
RUN mkdir -p /smat
RUN wget https://midialignment.github.io/AlignmentTool_v190813.zip -O /smat/smat.zip
RUN unzip /smat/smat.zip -d /smat
# this is the command that fails

#clone project and install requirements
RUN git clone --branch TPL https://github.com/trompamusic/trompa-align
RUN python3 -m pip install -r /trompa-align/requirements.txt
RUN Rscript /trompa-align/scripts/install-packages.R


RUN cd /smat/AlignmentTool_v190813 && ./compile.sh
