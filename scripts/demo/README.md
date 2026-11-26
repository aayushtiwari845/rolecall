# Recording the README demo

The GIF and MP4 in `docs/media/` come from these scripts, run against a local stack
(API on :8000, web on :3000, a crawled index).

```bash
python -m venv .rec && .rec/bin/pip install playwright==1.49.1 imageio-ffmpeg==0.5.1
.rec/bin/python -m playwright install chromium
mkdir -p /tmp/demo
.rec/bin/python setup.py /tmp/demo       # fictional demo account, resume PDF, preferences
.rec/bin/python record.py /tmp/demo      # ~1 minute; prints each scene's length
.rec/bin/python encode.py /tmp/demo ../../docs/media
```

`setup.py` signs in with the development login, so it only works where `ENV` is not
`production`. Each scene is preceded by a one-frame magenta marker that `encode.py`
finds in the video, so cuts are frame-accurate whatever the page load times.
