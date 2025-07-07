#!/bin/bash
set -e
chmod +x .devcontainer/setup.sh
sudo apt-get update

# install ffmpeg package
sudo apt-get install -y ffmpeg

# set up backend env
cd backend
python3 -m pip install -r requirements.txt

# set up frontend env
cd ../frontend
npm install