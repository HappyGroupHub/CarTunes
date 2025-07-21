#!/bin/bash
set -e

# Add uv to PATH for this session
export PATH="$HOME/.cargo/bin:$PATH"

# install ffmpeg package
sudo apt-get install -y ffmpeg

# set up backend env
cd backend
uv sync

# set up frontend env
cd ../frontend
npm install