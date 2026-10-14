#!/usr/bin/env python3
from pathlib import Path
import importlib.util, json, os, subprocess, sys, tempfile
ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'src/ipod_sync.py'
spec=importlib.util.spec_from_file_location('ipod_sync_public_test',APP)
m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m)

cases={
    'F06/SCLD.mp3':'F06/SCLD.mp3',
    ':iTunes_Control:Music:F06:SCLD.mp3':'F06/SCLD.mp3',
    'iTunes_Control/Music/F06/SCLD.mp3':'F06/SCLD.mp3',
    'Music/F06/SCLD.mp3':'F06/SCLD.mp3',
}
for raw,want in cases.items():
    got=m._location_to_music_rel(raw)
    assert got==want,(raw,got,want)
for raw in ('../etc/passwd','F06/../evil.mp3','/tmp/nope.mp3','FXX/file.mp3'):
    try:m._location_to_music_rel(raw)
    except m.SyncError:pass
    else:raise AssertionError(f'unsafe location accepted: {raw}')

# Reproduce the real ffprobe edge: warning on stderr, valid JSON on stdout.
with tempfile.TemporaryDirectory() as td:
    td=Path(td); fake=td/'ffprobe'; audio=td/'sample.wma'; audio.write_bytes(b'x')
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "tag warning" >&2\ncat <<EOF\n{"streams":[{"sample_rate":"44100","duration":"303.966125","bit_rate":"192000"}],"format":{"duration":"303.966125","bit_rate":"193082"}}\nEOF\n')
    fake.chmod(0o755)
    old=os.environ.get('PATH',''); os.environ['PATH']=str(td)+os.pathsep+old
    try:
        assert m.probe_audio(audio)==(303966,192,44100)
    finally: os.environ['PATH']=old


# Source guard is filesystem-agnostic but still requires a dedicated RO mount.
with tempfile.TemporaryDirectory() as td:
    root=Path(td).resolve()
    original=m.read_mounts
    try:
        m.read_mounts=lambda:[("/dev/test",str(root),"ext4",{"ro","relatime"})]
        g=m.require_source_ro(root)
        assert g.fstype=="ext4"
        sub=root/"sub"; sub.mkdir()
        try:m.require_source_ro(sub)
        except m.SyncError:pass
        else:raise AssertionError("source subdirectory accepted instead of dedicated mountpoint")
        m.read_mounts=lambda:[("/dev/test",str(root),"ext4",{"rw","relatime"})]
        try:m.require_source_ro(root)
        except m.SyncError:pass
        else:raise AssertionError("writable source mount accepted")
    finally:m.read_mounts=original

signer=(ROOT/"native/sign-cdb.c").read_text()
for marker in ("EXPECT_"+"RND", "EXPECT_"+"IV", "EXPECT_"+"PRISTINE_SIG"):
    assert marker not in signer

v=subprocess.run([sys.executable,str(APP),'--version'],text=True,capture_output=True,check=True).stdout.strip()
assert '0.2.0-alpha.5' in v,v

text=APP.read_text()
assert ('audited-' + 'frozen') not in text
assert ('TEMPLATE_' + 'FALLBACK_PID') not in text
assert ('--no-' + 'frozen-v4') not in text
assert 'source != mountpoint' in text
print('public alpha unit tests: PASS')
