![License](https://img.shields.io/github/license/OliPi-Project/olipi-moode)
![Python](https://img.shields.io/badge/python-3.9+-blue)
![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi-red)
![Discord](https://img.shields.io/discord/1410910825870266391?logo=discord&logoColor=white&logoSize=auto&label=Discord&color=blue&link=https%3A%2F%2Fdiscord.gg%2Fpku67XsFEE)
![GitHub Release](https://img.shields.io/github/v/release/OliPi-Project/olipi-core?include_prereleases&sort=date&display_name=tag)

# OliPi Core

OliPi Core is the base for creating Python3 user interface to display on i2c/SPI screens with control via IR remote and/or GPIO buttons. And now with MPR121 capacitive touch module.

---

## ❔ What's new?

**<u>V0.3.0-pre</u>**

- Add support for MPR121 capacitive touch with a beginnings of gesture support
- Add independent debounce settings depending on input
- Add support for SSD1306 SPI with FBTFT "not tested"
- Add support for ST7789 2.4" & 2.8"
- Add invert options & diag, can be configured in ini
- Better rotary management with GPIO interup 
- And other odds and ends

## 📦 System requirements

- **Operating system**: Raspberry Pi Os .

- **Hardware**: 
  
      - Raspberry Pi (Zero 2W, 3, 4, 5) 
      - I2C/SPI Screen. 
      - IR receiver type TSOP38 or similar (if used)
      - Push Button and/or Rotary Encoder (if used)
      - MPR121 capacitive touch module (if used)

- **Screens supported**:
  
  | Screen      | Resolution | Diag (") | PPI | Color      | Script                       |
  | ----------- | ---------- | -------- | --- | ---------- | ---------------------------- |
  | SSD1309     | 128×64     | 2.49     | 58  | Monochrome | SSD1306.py                   |
  | SSD1306     | 128×64     | 0.96     | 149 | Monochrome | SSD1306.py                   |
  | SSD1306 SPI (Not Tested) | 128×64 | 0.96 | 149 | Monochrome | SSD1306SPI.py           |
  | SSD1315     | 128×64     | 0.96     | 149 | Monochrome | SSD1306.py                   |
  | SSD1351     | 128×128    | 1.5      | 120 | RGB        | SSD1351.py                   |
  | ST7735R     | 128×160    | 1.77     | 116 | RGB        | ST7735R.py                   |
  | ST7789 1.9" | 170×320    | 1.9      | 191 | RGB        | ST7789W.py                   |
  | ST7789 2" 2.4" 2.8" | 240×320 | 2.0   | 200 | RGB      | ST7789V.py                   |

- **APT dependencies**:
  
  ```
  git python3-pil python3-venv python3-pip python3-tk libasound2-dev libatlas-base-dev libopenblas0-pthread libgfortran5 i2c-tools libgpiod-dev python3-libgpiod python3-lgpio python3-setuptools
  ```

- **Python dependencies**:
  
  ```
  luma.oled>=3.14.0
  luma_core>=2.5.2
  Pillow>=12.0.0
  PyYAML>=6.0.3
  rpi_lgpio>=0.6
  numpy>=2.3.4
  ```


### More Documentation to come ...


## 📄 License

License and attribution

This project is licensed under the GNU General Public License v3.0 (GPLv3).  
See the [LICENSE](./LICENSE) file for details.

## ⚠️ **Disclaimer**

The software and other items in this repository are distributed under the [GNU General Public License Version 3](https://github.com/Trachou2Bois/olipi-moode/blob/main/LICENSE), which includes the following disclaimer:

> 15. Disclaimer of Warranty.  
>     THERE IS NO WARRANTY FOR THE PROGRAM, TO THE EXTENT PERMITTED BY APPLICABLE LAW. EXCEPT WHEN OTHERWISE STATED IN WRITING THE COPYRIGHT HOLDERS AND/OR OTHER PARTIES PROVIDE THE PROGRAM "AS IS" WITHOUT WARRANTY OF ANY KIND, EITHER EXPRESSED OR IMPLIED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE. THE ENTIRE RISK AS TO THE QUALITY AND PERFORMANCE OF THE PROGRAM IS WITH YOU. SHOULD THE PROGRAM PROVE DEFECTIVE, YOU ASSUME THE COST OF ALL NECESSARY SERVICING, REPAIR OR CORRECTION.
> 
> 16. Limitation of Liability.  
>     IN NO EVENT UNLESS REQUIRED BY APPLICABLE LAW OR AGREED TO IN WRITING WILL ANY COPYRIGHT HOLDER, OR ANY OTHER PARTY WHO MODIFIES AND/OR CONVEYS THE PROGRAM AS PERMITTED ABOVE, BE LIABLE TO YOU FOR DAMAGES, INCLUDING ANY GENERAL, SPECIAL, INCIDENTAL OR CONSEQUENTIAL DAMAGES ARISING OUT OF THE USE OR INABILITY TO USE THE PROGRAM (INCLUDING BUT NOT LIMITED TO LOSS OF DATA OR DATA BEING RENDERED INACCURATE OR LOSSES SUSTAINED BY YOU OR THIRD PARTIES OR A FAILURE OF THE PROGRAM TO OPERATE WITH ANY OTHER PROGRAMS), EVEN IF SUCH HOLDER OR OTHER PARTY HAS BEEN ADVISED OF THE POSSIBILITY OF SUCH DAMAGES.

This means the user of this software is responsible for any damage resulting from its use, regardless of whether it is caused by misuse or by a bug in the software.
