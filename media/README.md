# Research demonstration

The repository README embeds a GitHub video attachment rather than linking a
poster to a raw file. GitHub's file browser is not an inline video player.

- `demo.mp4`: full-resolution 1920 × 1080 research demonstration.
- `demo-web.mp4`: 1280 × 720 inline copy, 120 seconds, 24 fps, silent H.264.
- `poster.png`: research summary cover.

The visible video and cover contain no conference name, submission identifier,
or submission-status label. The web copy strips source metadata; it preserves
the same frames, timing, evidence and conclusions without interpolation.

Attachment: https://github.com/user-attachments/assets/8ea7ec5d-82f2-4cc8-bb14-24ee3c0eb5b1

SHA-256:

```text
eaa7f704a52052d93665c26954e2c6a40e7b281692e39999f6d56132f59b14f6  demo.mp4
b77e3b733c368ac727e1e2a90b6e55e9856ff5a28eb442cbc7ed44e50acd57b9  demo-web.mp4
```

Web encoding:

```sh
ffmpeg -i demo.mp4 -map_metadata -1 -vf scale=1280:720 \
  -c:v libx264 -preset fast -b:v 530k -maxrate 650k -bufsize 1300k \
  -pix_fmt yuv420p -an -movflags +faststart demo-web.mp4
```

Dataset attribution and reuse conditions: [DATA_SOURCES.md](../DATA_SOURCES.md).

