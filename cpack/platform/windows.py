"""Windows: not in slice 1 (D8: Mac first). What this file needs, so the rest of the pack can stay as it is:
  data_home       %USERPROFILE%\\Videos\\Creator Pack
  tool            where.exe, plus the winget install folders
  install_steps   winget install Gyan.FFmpeg / OpenJS.NodeJS; whisper.cpp release zip (CUDA build if an NVIDIA card)
  whisper_device  NVIDIA CUDA, else the processor
  VIDEO_ENCODER   h264_nvenc if NVIDIA, else libx264; HWACCEL ['-hwaccel', 'auto']
  pick_files      PowerShell System.Windows.Forms.OpenFileDialog
  reveal          explorer /select,
  FONTS           C:\\Windows\\Fonts\\arialbd.ttf
Tested on a real Windows PC with an NVIDIA card before it ships (CT-128)."""
NAME = 'windows'


def _todo(*_a, **_k):
    raise NotImplementedError('The creator pack runs on a Mac for now. Windows comes in a later version.')


data_home = tool = whisper_model = whisper_device = font = font_heavy = font_cjk = han = install_steps = pick_files = reveal = open_url = _todo
