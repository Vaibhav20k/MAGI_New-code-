#!/bin/sh
# Joins the rendered picture with the voice-over into the final file. Runs on the server, inside the backend image (it has ffmpeg).
set -e
cd ~/video-work/turmeric
IMG=$(sudo docker inspect --format '{{.Image}}' marketing-mai-backend-1)
sudo docker run --rm -v "$PWD":/w -w /w --entrypoint sh "$IMG" -c '
ffmpeg -v error -y -i picture.mp4 -i narration.wav -map 0:v -map 1:a \
  -c:v libx264 -preset slow -crf 21 -maxrate 6M -bufsize 12M -pix_fmt yuv420p -r 30 \
  -af "loudnorm=I=-16:TP=-1.5:LRA=11" -c:a aac -b:a 160k -ar 48000 -ac 2 -t 30 -movflags +faststart the-turmeric-test.mp4
ffprobe -v error -show_entries stream=codec_name,width,height,nb_frames -show_entries format=duration,size,bit_rate -of default=nw=1 the-turmeric-test.mp4
ffmpeg -hide_banner -i the-turmeric-test.mp4 -af volumedetect -vn -f null - 2>&1 | grep -E "mean_volume|max_volume"
rm -rf check; mkdir -p check
for t in 0.5 4.0 8.9 12.0 14.9 17.6 21.0 23.2 24.0 27.5; do ffmpeg -v error -y -ss $t -i the-turmeric-test.mp4 -frames:v 1 -vf scale=540:-1 check/f$t.jpg; done
'
sudo chown -R ubuntu .
ls -la
