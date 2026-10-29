"""打包入口：PyInstaller 从这里进。"""
import sys

from kitty.main import main

if __name__ == "__main__":
    sys.exit(main())
