import os
import datetime
import math
import base64
import sys
import time

IVT_SIZE = 256 # векторы

class VideoController:
    def __init__(self):
        self.set_video_mode(0x03)  # Инициализация текстового режима по умолчанию
        self.attr = 0x07  # Светло-серый на черном
        
    def set_video_mode(self, mode):
        if mode == 0x03:
            self.width = 80
            self.height = 25
            self.vram = [0] * (self.width * self.height * 2)
            self.cursor_x = 0
            self.cursor_y = 0
            self.clear_screen()
            
    def show_video_output(self):
        output = []
        for y in range(self.height):
            line = []
            for x in range(self.width):
                pos = (y * self.width + x) * 2
                char = self.vram[pos]
                attr = self.vram[pos+1]
                fg = 30 + (attr & 0x0F)
                bg = 40 + ((attr >> 4) & 0x07)
                line.append(f"\x1b[{fg};{bg}m{chr(char) if char else ' '}")
            output.append(''.join(line))
        print("\x1b[H" + "\n".join(output) + "\x1b[0m", end='', flush=True)

    def put_char(self, char, attr):
        # Обработка специальных символов
        if char == '\n':
            self.new_line()
            return
        elif char == '\r':
            self.cursor_x = 0
            return
        elif char == '\b':
            self.cursor_x = max(0, self.cursor_x-1)
            self.put_char(' ', attr)
            return
            
        # Запись символа в видеопамять
        pos = (self.cursor_y * self.width + self.cursor_x) * 2
        if pos + 1 < len(self.vram):
            self.vram[pos] = ord(char)
            self.vram[pos+1] = attr
            
        self.cursor_x += 1
        if self.cursor_x >= self.width:
            self.new_line()
            
    def new_line(self):
        self.cursor_x = 0
        self.cursor_y += 1
        if self.cursor_y >= self.height:
            self.vram = self.vram[self.width*2:] + [0]*(self.width*2)
            self.cursor_y = self.height - 1

    def handle_int10(self, cpu):
        ah = (cpu.registers['AX'] >> 8) & 0xFF
        al = self.registers['AX'] & 0xFF

        if ah == 0x00:
            self.set_video_mode(al)
        elif ah == 0x02:
            self.cursor_y = cpu.registers['DX'] >> 8
            self.cursor_x = cpu.registers['DX'] & 0xFF
        elif ah == 0x0E:
            self.put_char(chr(al), self.attr)
        
    def handle_vblank(self):
        self.vblank = True
        self.blink_state = not self.blink_state
    
    def check_ansi_support(self):
        try:
            import os
            if os.name == 'nt':
                from colorama import just_fix_windows_console
                just_fix_windows_console()
            else:
                self.use_ansi = 'TERM' in os.environ and 'xterm' in os.environ['TERM']
        except:
            self.use_ansi = False

    def clear_screen(self):
        if self.video_mode == 0x03:
            self.vram = bytearray([0x20, 0x07] * (self.width * self.height))
        else:
            self.vram = bytearray([0] * len(self.vram))
        self.cursor_x = 0
        self.cursor_y = 0
        self.dirty_rects = [(0, 0, self.width, self.height)]

    def scroll_screen(self):
        if self.video_mode == 0x03:
            self.vram = self.vram[self.width*2:] + bytearray([0x20, 0x07]*self.width)
        else:
            self.vram = self.vram[self.width:] + bytearray([0]*self.width)
        self.cursor_y = max(0, self.height - 1)
        self.dirty_rects = [(0, 0, self.width, self.height)]

    def scroll(self):
       self.vram = self.vram[self.width:] + [0x0720]*self.width
       self.cursor_y = self.height - 1

    def get_display(self):
        return '\n'.join(
            ''.join(chr(c & 0xFF) for c in self.vram[y*self.width:(y+1)*self.width])
            for y in range(self.height)
        )
            
    def swap_buffers(self):
        self.vram, self.back_buffer = self.back_buffer, self.vram
        self.dirty_rects = [(0, 0, self.width, self.height)]

    def draw_lines(self, x0, y0, x1, y1, color):  
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        
        while True:
            self.draw_pixel(x0, y0, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy
    
    def draw_image(self, x, y, image_data):
        ptr = 0
        while ptr < len(image_data):
            count = image_data[ptr]
            color = image_data[ptr+1]
            ptr += 2
            for i in range(count):
                px_x = (x + (i % self.width)) % self.width
                px_y = y + (i // self.width)
                self.draw_pixel(px_x, px_y, color)
    
    def set_color(self, color, rgb=None):
        if rgb:
            self.attr = 0x01
            self.palette[0] = rgb
        else:
            self.attr = color & 0xFF
            
    def create_gradient(self, width, height, colors):
        key = f"{width}x{height}-{'-'.join(map(str, colors))}"
        if key not in gradient_cache:
            gradient = []
            for y in range(height):
                for x in range(width):
                    ratio = (x + y) / (width + height)
                    r = int(colors[0][0] * (1 - ratio) + colors[1][0] * ratio)
                    g = int(colors[0][1] * (1 - ratio) + colors[1][1] * ratio)
                    b = int(colors[0][2] * (1 - ratio) + colors[1][2] * ratio)
                    gradient.append((r, g, b))
            self.gradient_cache[key] = gradient
        return self.gradient_cache[key]
        
    def draw_pixel(self, x, y, color):
        if 0 <= x < self.width and 0 <= y < self.height:
            if self.video_mode == 0x13:  # 320x200x256
                self.vram[y * self.width + x] = color
            elif self.video_mode == 0x12:  # 640x480x16
                pos = y * (self.width // 2) + (x // 2)
                if x % 2 == 0:
                    self.vram[pos] = (self.vram[pos] & 0x0F) | (color << 4)
                else:
                    self.vram[pos] = (self.vram[pos] & 0xF0) | color
            self.dirty_rects.append((x, y, 1, 1))
            
    def init_graphic_mode(self):
        self.modes = {
            0x13: (320, 200, 256)
        }
        self.framebuffer = []

    def get_display_output(self):
        output = []
        for y in range(25):
            line = []
            for x in range(80):
                pos = (y * 80 + x) * 2
                line.append(chr(self.video_memory[pos]))
            output.append(''.join(line))
        return '\n'.join(output)

    def _render_text_mode(self):
        output = []
        for y in range(self.height):
            line = []
            for x in range(self.width):
                pos = y * self.width * 2 + x * 2
                char_code = self.vram[pos]
                attr = self.vram[pos+1]
                
                # Упрощенная конвертация в ANSI
                ansi = f"\x1b[{attr//16 + 40};{attr%16 + 30}m{chr(char_code)}"
                line.append(ansi)
            output.append(''.join(line))
        return '\n'.join(output)

    def _render_256color_mode(self):
        output = []
        for y in range(0, self.height, 2):
            line = []
            for x in range(self.width):
                top = self.vram[y * self.width + x]
                bottom = self.vram[(y+1) * self.width + x] if y+1 < self.height else 0
                line.append(f"\x1b[38;5;{top}m\x1b[48;5;{bottom}m▄")
            output.append(''.join(line))
        return '\n'.join(output)

    def _render_16color_mode(self):
        output = []
        for y in range(self.height):
            line = []
            for x in range(0, self.width, 2):
                byte = self.vram[y * (self.width//2) + x//2]
                fg = byte >> 4
                bg = byte & 0x0F
                line.append(f"\x1b[38;5;{fg}m\x1b[48;5;{bg}m▀")
                output.append(''.join(line))
        return '\n'.join(output)

    def write_crtc_register(self, index, value):
        if index < len(self.crtc_registers):
            self.crtc_registers[index] = value
                
    def set_dac_color(self, index, r, g, b):
        self.dac_palette[index] = (r, g, b)
            
    def handle_vblank(self):
        self.vblank = True
        self.blink_state = not self.blink_state
            
    def draw_glyph(self, x, y, char_code, fg, bg):
        if self.font and char_code in self.font:
            for row in range(16):
                bits = self.font[char_code][row]
                for col in range(8):
                    if bits[col]:
                        self.draw_pixel(x + col, y + row, fg)
                    else:
                        self.draw_pixel(x + col, y + row, bg)
        else:
            self.draw_pixel(x, y, fg)
            self.draw_pixel(x+1, y, fg)
            self.draw_pixel(x, y+1, fg)
            self.draw_pixel(x+1, y+1, fg)
                       
    def get_ascii_output(self):
        output = []
        for y in range(self.height):
            line = []
            for x in range(self.width):
                pos = (y * self.width + x) * 2
                char_code = self.vram[pos]
                line.append(chr(char_code) if 32 <= char_code < 127 else ' ')
            output.append(''.join(line))
        return '\n'.join(output)

class PetyshCore16:
    def __init__(self):
        self.video_output = None
        self.vc = VideoController()  # ммм ютубчик
        self.keyboard_buffer = [] # клава
        self.disk_data = {0: b"Boot sector"} # типо диск
        self.timer_ticks = 0
        self.rtc_time = datetime.datetime.now()
        self.interrupt_enabled = True
        self.debug_mode = False
        self.breakpoints = set()
        self.os_loaded = False
        self.programs_dir = "programs/"
        self.gpu_accelerated = False
        self.ports = [0] * 65536 # 64KB
        self.ports[0x60] = 0 # клава (НЕ БУФЕР)
        self.memory = [0x00] * 1048576
        self.load_basic_font()
        self.vc.set_video_mode(0x03)
        self.video_functions = {
            0x10: self.handle_video_interrupt,
            0x11: self.handle_font_interrupt
        }
        self.video_modes = {
            0x13: (40, 25, 16),    # Текстовый режим
            0x5A: (80, 50, 256),   # Псевдографический
            0x5B: (160, 100, 65536) # RGB режим
        }
        # 16-битные регистры
        self.registers = {
            'AX': 0x0000,
            'BX': 0x0000,
            'CX': 0x0000,
            'DX': 0x0000,
            'IP': 0x0000,
            'SP': 0xFFFF,
            'FLAGS': 0b00000000
        }

        self.registers.update({
            'CS': 0x0000,
            'DS': 0x0000,
            'ES': 0x0000,
            'SS': 0x0000,
            'SI': 0x0000,
            'DI': 0x0000,
            'BP': 0x0000,
        })
        
        self.rep_prefix = False
        self.direction_flag = False
        self.reg_names = ['AX', 'BX', 'CX', 'DX']

        self.ivt = [0x0000] * IVT_SIZE # каждая запись
        self.memory = [0x00] * 1048576 # 1мб
        self.memory_map = [False] * 65536 # карта занятой памяти
        self.memory_map[0x0000:0x0400] = [True]*0x0400 # ivt
        self.memory_blocks = {} # блоки памяти (выделенной)
        self.current_mcb = 0x0000 # memory control block
        
        self.gdt = [
            {'base': 0, 'limit': 0, 'access': 0x00},  # Нулевой дескриптор
            {'base': 0, 'limit': 0xFFFFF, 'access': 0x9A},  # Код сегмент
            {'base': 0, 'limit': 0xFFFFF, 'access': 0x92}   # Данные сегмент
        ]
        self.ldt = []
        self.gdtr = {'base': 0, 'limit': 0}
        self.ldtr = 0
        
        self.commands = {
            'help': self.cmd_help,
            'cls': self.cmd_cls,
            'run': self.cmd_run,
            'list': self.cmd_list,
            'meminfo': self.cmd_meminfo,
            'edit': self.cmd_edit
        }
        self.prompt = "\x1b[32mPCI1~$\x1b[0m "
        self.history = []

    def load_basic_font(self):
        """Загрузка базового 8x16 шрифта"""
        # Базовый шрифт с ASCII символами (0x20-0x7F)
        font = [
                        # Пробел (0x20)
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            # ! (0x21)
            0x00, 0x00, 0x18, 0x3C, 0x3C, 0x3C, 0x18, 0x18, 0x18, 0x00, 0x18, 0x18, 0x00, 0x00, 0x00, 0x00,
            # " (0x22)
            0x00, 0x66, 0x66, 0x66, 0x24, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            # # (0x23)
            0x00, 0x00, 0x6C, 0x6C, 0xFE, 0x6C, 0x6C, 0x6C, 0xFE, 0x6C, 0x6C, 0x00, 0x00, 0x00, 0x00, 0x00,
            # $ (0x24)
            0x18, 0x18, 0x7C, 0xC6, 0xC2, 0xC0, 0x7C, 0x06, 0x06, 0x86, 0xC6, 0x7C, 0x18, 0x18, 0x00, 0x00,
            # % (0x25)
            0x00, 0x00, 0x00, 0x00, 0xC2, 0xC6, 0x0C, 0x18, 0x30, 0x60, 0xC6, 0x86, 0x00, 0x00, 0x00, 0x00,
            # & (0x26)
            0x00, 0x00, 0x38, 0x6C, 0x6C, 0x38, 0x76, 0xDC, 0xCC, 0xCC, 0xCC, 0x76, 0x00, 0x00, 0x00, 0x00,
            # ' (0x27)
            0x00, 0x30, 0x30, 0x30, 0x60, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            # ( (0x28)
            0x00, 0x00, 0x0C, 0x18, 0x30, 0x30, 0x30, 0x30, 0x30, 0x30, 0x18, 0x0C, 0x00, 0x00, 0x00, 0x00,
            # ) (0x29)
            0x00, 0x00, 0x30, 0x18, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x18, 0x30, 0x00, 0x00, 0x00, 0x00,
            # * (0x2A)
            0x00, 0x00, 0x00, 0x00, 0x00, 0x66, 0x3C, 0xFF, 0x3C, 0x66, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            # + (0x2B)
            0x00, 0x00, 0x00, 0x00, 0x00, 0x18, 0x18, 0x7E, 0x18, 0x18, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            # , (0x2C)
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x18, 0x18, 0x18, 0x30, 0x00, 0x00, 0x00,
            # - (0x2D)
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x7E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            # . (0x2E)
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x18, 0x18, 0x18, 0x00, 0x00, 0x00, 0x00,
            # / (0x2F)
            0x00, 0x00, 0x00, 0x00, 0x02, 0x06, 0x0C, 0x18, 0x30, 0x60, 0xC0, 0x80, 0x00, 0x00, 0x00, 0x00,
            # 0 (0x30)
            0x00, 0x00, 0x7C, 0xC6, 0xC6, 0xCE, 0xDE, 0xF6, 0xE6, 0xC6, 0xC6, 0x7C, 0x00, 0x00, 0x00, 0x00,
            # 1 (0x31)
            0x00, 0x00, 0x18, 0x38, 0x78, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x7E, 0x00, 0x00, 0x00, 0x00,
            # 2 (0x32)
            0x00, 0x00, 0x7C, 0xC6, 0x06, 0x0C, 0x18, 0x30, 0x60, 0xC0, 0xC6, 0xFE, 0x00, 0x00, 0x00, 0x00,
            # 3 (0x33)
            0x00, 0x00, 0x7C, 0xC6, 0x06, 0x06, 0x3C, 0x06, 0x06, 0x06, 0xC6, 0x7C, 0x00, 0x00, 0x00, 0x00,
            # 4 (0x34)
            0x00, 0x00, 0x3C, 0x66, 0x66, 0x60, 0x60, 0x7C, 0x60, 0x60, 0x60, 0x7E, 0x00, 0x00, 0x00, 0x00,
            # 5 (0x35)
            0x00, 0x00, 0x7E, 0x60, 0x60, 0x7C, 0x06, 0x06, 0x06, 0x06, 0x66, 0x3C, 0x00, 0x00, 0x00, 0x00,
            # 6 (0x36)
            0x00, 0x00, 0x3C, 0x66, 0x66, 0x66, 0x7C, 0x60, 0x60, 0x60, 0x66, 0x3C, 0x00, 0x00, 0x00, 0x00,
            # 7 (0x37)
            0x00, 0x00, 0x7E, 0x06, 0x06, 0x0C, 0x0C, 0x18, 0x18, 0x30, 0x30, 0x30, 0x00, 0x00, 0x00, 0x00,
            # 8 (0x38)
            0x00, 0x00, 0x3C, 0x66, 0x66, 0x66, 0x3C, 0x66, 0x66, 0x66, 0x66, 0x3C, 0x00, 0x00, 0x00, 0x00,
            # 9 (0x39)
            0x00, 0x00, 0x3C, 0x66, 0x66, 0x66, 0x3E, 0x06, 0x06, 0x06, 0x66, 0x3C, 0x00, 0x00, 0x00, 0x00,
            # : (0x3A)
            0x00, 0x00, 0x00, 0x00, 0x18, 0x18, 0x00, 0x00, 0x18, 0x18, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            # ; (0x3B)
            0x00, 0x00, 0x00, 0x00, 0x18, 0x18, 0x00, 0x00, 0x18, 0x18, 0x30, 0x00, 0x00, 0x00, 0x00, 0x00,
            # < (0x3C)
            0x00, 0x00, 0x00, 0x06, 0x0C, 0x18, 0x30, 0x60, 0x30, 0x18, 0x0C, 0x06, 0x00, 0x00, 0x00, 0x00,
            # = (0x3D)
            0x00, 0x00, 0x00, 0x00, 0x7E, 0x00, 0x00, 0x7E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            # > (0x3E)
            0x00, 0x00, 0x00, 0x60, 0x30, 0x18, 0x0C, 0x06, 0x0C, 0x18, 0x30, 0x60, 0x00, 0x00, 0x00, 0x00,
            # ? (0x3F)
            0x00, 0x00, 0x3C, 0x66, 0x66, 0x0C, 0x18, 0x18, 0x18, 0x00, 0x18, 0x18, 0x00, 0x00, 0x00, 0x00,
            # @ (0x40)
            0x00, 0x00, 0x3C, 0x42, 0x99, 0xA5, 0xA5, 0xA5, 0xA5, 0x9E, 0x40, 0x3C, 0x00, 0x00, 0x00, 0x00,
            # A (0x41)
            0x00, 0x00, 0x18, 0x3C, 0x66, 0x66, 0x7E, 0x66, 0x66, 0x66, 0x66, 0x66, 0x00, 0x00, 0x00, 0x00,
            # B (0x42)
            0x00, 0x00, 0x7C, 0x66, 0x66, 0x66, 0x7C, 0x66, 0x66, 0x66, 0x66, 0x7C, 0x00, 0x00, 0x00, 0x00,
            # C (0x43)
            0x00, 0x00, 0x3C, 0x66, 0x66, 0x60, 0x60, 0x60, 0x60, 0x66, 0x66, 0x3C, 0x00, 0x00, 0x00, 0x00,
            # D (0x44)
            0x00, 0x00, 0x7C, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x7C, 0x00, 0x00, 0x00, 0x00,
            # E (0x45)
            0x00, 0x00, 0x7E, 0x60, 0x60, 0x60, 0x7C, 0x60, 0x60, 0x60, 0x60, 0x7E, 0x00, 0x00, 0x00, 0x00,
            # F (0x46)
            0x00, 0x00, 0x7E, 0x60, 0x60, 0x60, 0x7C, 0x60, 0x60, 0x60, 0x60, 0x60, 0x00, 0x00, 0x00, 0x00,
            # G (0x47)
            0x00, 0x00, 0x3C, 0x66, 0x66, 0x60, 0x60, 0x6E, 0x66, 0x66, 0x66, 0x3C, 0x00, 0x00, 0x00, 0x00,
            # H (0x48)
            0x00, 0x00, 0x66, 0x66, 0x66, 0x66, 0x7E, 0x66, 0x66, 0x66, 0x66, 0x66, 0x00, 0x00, 0x00, 0x00,
            # I (0x49)
            0x00, 0x00, 0x3C, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x3C, 0x00, 0x00, 0x00, 0x00,
            # J (0x4A)
            0x00, 0x00, 0x1E, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x6C, 0x6C, 0x38, 0x00, 0x00, 0x00, 0x00,
            # K (0x4B)
            0x00, 0x00, 0x66, 0x66, 0x6C, 0x6C, 0x78, 0x78, 0x6C, 0x6C, 0x66, 0x66, 0x00, 0x00, 0x00, 0x00,
            # L (0x4C)
            0x00, 0x00, 0x60, 0x60, 0x60, 0x60, 0x60, 0x60, 0x60, 0x60, 0x60, 0x7E, 0x00, 0x00, 0x00, 0x00,
            # M (0x4D)
            0x00, 0x00, 0x63, 0x77, 0x7F, 0x6B, 0x6B, 0x6B, 0x63, 0x63, 0x63, 0x63, 0x00, 0x00, 0x00, 0x00,
            # N (0x4E)
            0x00, 0x00, 0x66, 0x66, 0x76, 0x76, 0x7E, 0x6E, 0x6E, 0x66, 0x66, 0x66, 0x00, 0x00, 0x00, 0x00,
            # O (0x4F)
            0x00, 0x00, 0x3C, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x3C, 0x00, 0x00, 0x00, 0x00,
            # P (0x50)
            0x00, 0x00, 0x7C, 0x66, 0x66, 0x66, 0x66, 0x7C, 0x60, 0x60, 0x60, 0x60, 0x00, 0x00, 0x00, 0x00,
            # Q (0x51)
            0x00, 0x00, 0x3C, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x6E, 0x6C, 0x36, 0x00, 0x00, 0x00, 0x00,
            # R (0x52)
            0x00, 0x00, 0x7C, 0x66, 0x66, 0x66, 0x66, 0x7C, 0x6C, 0x66, 0x66, 0x66, 0x00, 0x00, 0x00, 0x00,
            # S (0x53)
            0x00, 0x00, 0x3C, 0x66, 0x66, 0x60, 0x38, 0x0C, 0x06, 0x66, 0x66, 0x3C, 0x00, 0x00, 0x00, 0x00,
            # T (0x54)
            0x00, 0x00, 0x7E, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x00, 0x00, 0x00, 0x00,
            # U (0x55)
            0x00, 0x00, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x3C, 0x00, 0x00, 0x00, 0x00,
            # [ (0x5B)
            0x00, 0x00, 0x3C, 0x30, 0x30, 0x30, 0x30, 0x30, 0x30, 0x30, 0x30, 0x3C, 0x00, 0x00, 0x00, 0x00,
            # \ (0x5C)
            0x00, 0x00, 0x00, 0x80, 0xC0, 0x60, 0x30, 0x18, 0x0C, 0x06, 0x03, 0x01, 0x00, 0x00, 0x00, 0x00,
            # ] (0x5D)
            0x00, 0x00, 0x3C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x3C, 0x00, 0x00, 0x00, 0x00,
            # ^ (0x5E)
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            # _ (0x5F)
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x7E, 0x00, 0x00, 0x00, 0x00,
            # ` (0x60)
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
        ]
        # Fill remaining characters with empty data
        while len(font) < 256 * 16:
            font.append(0x00)
        
        # Corrected call to load_font with all required arguments
        self.vc.load_font('default', bytes(font[:256*16]), 8, 16)

    def terminal_loop(self):
        """Основной цикл терминала"""
        print("\x1b[2J\x1b[H")  # Очистка экрана
        
        while True:
            try:
                cmd = input(self.prompt).strip()
                if not cmd:
                    continue
                    
                self.history.append(cmd)
                parts = cmd.split()
                command = parts[0].lower()
                args = parts[1:]
                
                if command in self.commands:
                    self.commands[command](args)
                else:
                    self.execute_binary_command(cmd)
                    
            except KeyboardInterrupt:
                print("\nUse 'exit' to quit")
            except Exception as e:
                print(f"\x1b[31mError: {str(e)}\x1b[0m")

    def cmd_help(self, args):
        """Вывод списка команд"""
        help_text = """
        Available commands:
        cls       - Очистить экран
        run <bin> - Запустить бинарный файл
        list      - Показать файлы в директории программ
        meminfo   - Показать информацию о памяти
        edit <f>  - Редактировать файл (базовый редактор)
        exit      - Выйти из эмулятора
        help      - Показать эту справку
        """
        print(help_text)

    def cmd_cls(self, args):
        """Очистка экрана"""
        self.vc.clear_screen()
        print("\x1b[2J\x1b[H")

    def cmd_run(self, args):
        """Запуск бинарного файла"""
        if not args:
            print("Usage: run <filename.bin>")
            return
            
        filename = args[0]
        try:
            with open(os.path.join(self.programs_dir, filename), "rb") as f:
                program = list(f.read())
            self.load_program(program)
            self.registers['IP'] = 0
            self.os_loaded = True  # Добавлено: Устанавливаем флаг загрузки ОС
            print(f"Running {filename}...\n")
            self.execute_program()  # Запускаем выполнение программы
        except Exception as e:
            print(f"\x1b[31mFailed to run {filename}: {str(e)}\x1b[0m")

    def cmd_list(self, args):
        """Показать файлы в директории программ"""
        try:
            files = os.listdir(self.programs_dir)
            print("Programs directory:")
            for f in files:
                print(f"  - {f}")
        except Exception as e:
            print(f"\x1b[31mCan't list directory: {str(e)}\x1b[0m")

    def cmd_meminfo(self, args):
        """Информация о памяти"""
        used = sum(self.memory_map)
        total = len(self.memory_map)
        print(f"Memory usage: {used/1024:.1f} KB / {total/1024:.1f} KB")
        print(f"Allocated blocks: {len(self.memory_blocks)}")
        print(f"Video memory: {len(self.vc.vram)} bytes")

    def cmd_edit(self, args):
        """Простой текстовый редактор"""
        if not args:
            print("Usage: edit <filename>")
            return
            
        filename = args[0]
        try:
            with open(os.path.join(self.programs_dir, filename), "r") as f:
                content = f.read()
        except FileNotFoundError:
            content = ""
            
        print(f"Editing {filename} (Ctrl+D to save, Ctrl+C to cancel)")
        new_content = []
        try:
            while True:
                line = input()
                new_content.append(line)
        except EOFError:
            pass  # Сохранение файла
        except KeyboardInterrupt:
            print("\nCanceled")
            return
            
        with open(os.path.join(self.programs_dir, filename), "w") as f:
            f.write("\n".join(new_content))
        print(f"File {filename} saved")

    def execute_program(self):
        """Выполнение загруженной программы"""
        try:
            while self.os_loaded:
                self.execute()
                self.vc.show_video_output()
                time.sleep(0.01)
        except Exception as e:
            print(f"\x1b[31mProgram crashed: {str(e)}\x1b[0m")
        finally:
            self.os_loaded = False

    def execute_binary_command(self, cmd):
        """Выполнение бинарной команды напрямую"""
        if cmd == "exit":
            self.shutdown()
        else:
            print(f"\x1b[31mUnknown command: {cmd}\x1b[0m")

    def update_arithmetic_flags(self, result):
        self.registers['FLAGS'] = 0b00000000

        value = result & 0xFFFF

        # нулевой
        if value == 0:
            self.registers['FLAGS'] |= 0b00000001

        if value & 0x8000:
            self.registers['FLAGS'] |= 0b00000010

        if result != value:
            self.registers['FLAGS'] |= 0b00000100

        if (result < -32768) or (result > 32767):
            self.registers['FLAGS'] |= 0b00001000

        if (result & 0xFFFF0000) != 0:
            self.registers['FLAGS'] |= 0b00010000

    def set_breakpoint(self, address):
        self.breakpoints.add(address)

    def single_step(self):
        old_ip = self.registers['IP']
        if self.memory[old_ip] == 0xCD:
            self.execute_int()
        else:
            self.execute_instruction()
        return old_ip

    def load_program(self, program):
        for i, byte in enumerate(program):
            self.memory[i] = byte

    def fetch_instruction(self):
        if self.registers['IP'] >= len(self.memory):
            self.handle_interrupt(0x00)
            return 0xFF
        return self.memory[self.registers['IP']]
    
        try:
            opcode = self.memory[self.registers['IP']]
        except IndexError:
            opcode = 0xFF
        self.registers['IP'] += 1
        return opcode

    def update_flags(self):
        self.registers['FLAGS'] = 0b00000000

        if self.registers['AX'] == 0:
            self.registers['FLAGS'] |= 0b00000001 # з флаг

        if self.registers['AX'] & 0x8000:
            self.registers['FLAGS'] |= 0b000000010 # с флаг

    # прерывания
    def handle_disk_interrupt(self):
        sector = self.registers['CX']
        address = (self.registers['ES'] << 4) + self.registers['BX']
        if sector in self.disk_data:
            data = self.disk_data[sector]
            for i, byte in enumerate(data):
                if address+i < len(self.memory):
                    self.memory[address+i] = byte
            self.registers['AX'] = 0x0000
        else:
            self.registers['AX'] = 0x0001

    def handle_rtc_interrupt(self):
        function = self.registers['AX'] & 0xFF
        if function == 0x00:
            # получение времени
            self.registers['CX'] = self.rtc_time.hour
            self.registers['DX'] = self.rtc_time.minute

    def handle_font_interrupt(self):
        function = self.registers['AX'] & 0xFF

        if function == 0x00:
            # загрузка шрифта
            name_ptr = (self.registers['DS'] << 4) + self.registers['SI']
            name = self.read_string(name_ptr)
            data_ptr = (self.registers['ES'] << 4) + self.registers['DI']
            width = self.registers['CX'] & 0xFF
            height = (self.registers['CX'] >> 8) & 0xFF
            length = self.registers['DX']
            font_data = bytes(self.memory[data_ptr:data_ptr+length])
            self.vc.load_font(name, font_data, width, height)
        elif function == 0x01:
            # установка текущего шрифта
            name_ptr = (self.registers['DS'] << 4) + self.registers['SI']
            name = self.read_string(name_ptr)
            self.vc.set_font(name)
        elif function == 0x02:  # Получение информации о шрифте
            name_ptr = (self.registers['DS'] << 4) + self.registers['SI']
            name = self.read_string(name_ptr)
            if name in self.vc.fonts:
                font = self.vc.fonts[name]
                self.registers['AX'] = font['width']
                self.registers['BX'] = font['height']
                self.registers['CX'] = len(font['data'])
            else:
                self.registers['AX'] = 0xFFFF

    def read_string(self, address):
        """чтение строки из памяти"""
        result = ""
        while self.memory[address] != 0:
            result += chr(self.memory[address])
            address += 1
        return result

    def handle_video_interrupt(self):
        function = self.registers['AX'] & 0xFF00
        subfunction = self.registers['AX'] & 0xFF
        ah = (self.registers['AX'] & 0xFF00) >> 8
        al = self.registers['AX'] & 0xFF

        if ah == 0x00:
            self.vc.set_video_mode(al)
        elif ah == 0x0E:
            char = chr(al)
            self.vc.put_char(char, self.vc.attr)
            self.vc.show_video_output()
            
        if (self.registers['AX'] & 0xFF00) == 0x0E00:
            char = self.registers['AX'] & 0xFF
            self.vc.put_char(char, 0x07)
            self.vc.dirty_rects = True

        if function == 0x0000:  # Set video mode
            self.vc.set_video_mode(subfunction)
        elif function == 0x0100:  # Set cursor shape
            self.vc.cursor_shape = (self.registers['CX'] >> 8, self.registers['CX'] & 0xFF)
        elif function == 0x0200:  # Set cursor position
            self.vc.cursor_y = self.registers['DX'] >> 8
            self.vc.cursor_x = self.registers['DX'] & 0xFF
        elif function == 0x0300:  # Get cursor info
            self.registers['CX'] = (self.vc.cursor_shape[0] << 8) | self.vc.cursor_shape[1]
            self.registers['DX'] = (self.vc.cursor_y << 8) | self.vc.cursor_x
        elif function == 0x0500:  # Select active page
            self.vc.active_page = subfunction
        elif function == 0x0800:  # Write char+attr
            char = self.registers['AX'] & 0xFF
            count = self.registers['CX']
            self.vc.put_char(char, self.registers['BX'], count)
        elif function == 0x1000:  # Set DAC color
            index = self.registers['BX']
            r = (self.registers['CX'] >> 8) & 0xFF
            g = self.registers['CX'] & 0xFF
            b = self.registers['DX'] >> 8
            self.vc.set_dac_color(index, r, g, b)
        elif function == 0x1001:
            addr = (self.registers['ES'] << 4) + self.registers['BX']
            font_data = bytes(self.memory[addr:addr+2048])
            self.vc.load_font(font_data)
        elif function == 0x1002:
            width = self.registers['CX']
            height = self.registers['DX']
            colors = [
                (self.registers['SI'] >> 8, self.registers['SI'] & 0xFF, self.registers['DI'] >> 8),
                (self.registers['DI'] & 0xFF, self.registers['BX'] >> 8, self.registers['BX'] & 0xFF)
            ]
            gradient = self.vc.create_gradient(width, height, colors)
        elif function == 0x1003:
            self.gpu_accelerated = True
        elif function == 0x0E00:  # Вывод символа (AH=0x0E)
            char = self.registers['AX'] & 0xFF
            self.put_char(char, 0x07)
            self.dirty_rects = True

    def handle_interrupt(self, int_num):
        if int_num >= IVT_SIZE:
            self.handle_memory_fault(0)
            return 
        
        # чета типа обработчика прерываний
        if int_num == 0x10:
            self.handle_video_interrupt()
        elif int_num == 0x13:
            # диски типо ну это для ос для этого проца это уже в будущем
            # продумал круто типо да?
            self.handle_disk_interrupt()
        elif int_num == 0x16:
            self.keyboard_interrupt() # клава типо
        elif int_num == 0x21:
            # дос
            self.handle_dos_interrupt()
        if int_num == 0x21 and (self.registers['AX'] >> 8) == 0x48:
            # DOS ALLOCATE MEMORY
            size = self.registers['BX']
            addr = self.allocate_memory(size)
            self.registers['AX'] = addr
        elif int_num == 0x21 and (self.registers['AX'] >> 8) == 0x49:
            # DOS FREE MEMORY
            ptr = self.registers['ES']
            self.free_memory(ptr)
        elif int_num == 0x1A:
            # RTC
            self.handle_rtc_interrupt()

        # сохранения состояний
        self.push(self.registers['IP'])
        self.push(self.registers['FLAGS'])

        # переход к обработчику
        self.registers['IP'] = self.ivt[int_num]

    def handle_dos_interrupt(self):
        function = self.registers['AX'] >> 8
        if function == 0x4C:
            self.os_loaded = False
        if function == 0x4B:
            filename_addr = (self.registers['DS'] << 4) + self.registers['DX']
            filename = ""
            while self.memory[filename_addr] != 0:
                filename += chr(self.memory[filename_addr])
                filename_addr += 1
            self.load_and_run_program(filename)

    def run_os_command(self, command):
        if command.startswith("run "):
            filename = command[4:].strip('"')
            self.load_and_run_program(filename)

    def load_and_run_program(self, filename):
        try:
            with open(f"{self.programs_dir}{filename}", "rb") as f:
                program = list(f.read())
            self.load_program(program)
            self.os_loaded = True
        except FileNotFoundError:
            print(f"Error: Program {filename} not found")
            return

    def video_interrupt(self):
        if self.registers['AX'] & 0xFF00 == 0x0E00:
            char = chr(self.registers['AX'] & 0x00FF)
            self.video_output.append(char)
            print(char, end='')

    # кулл стафф
    def disassemble(self, address):
        opcode = self.memory[address]
        if opcode == 0xA4:
            return "MOVSB"
        elif opcode == 0xA6:
            return "CMPSB"
        elif opcode == 0xAE:
            return "SCASB"
        if opcode == 0x01:
            return f"MOV {['AX','BX','CX','DX'][self.memory[address+1]]}, 0x{self.memory[address+2]:02X}{self.memory[address+3]:02X}"
        elif opcode == 0xFF:
            return "HLT"
        return f"DB 0x{opcode:02X}"

    def debug_info(self):
        print(f"AX: {self.registers['AX']:04X}  BX: {self.registers['BX']:04X}")
        print(f"IP: {self.registers['IP']:04X}  FLAGS: {bin(self.registers['FLAGS'])}")

    # крутая подсистема памяти

    def setup_memory_segments(self):
        self.segments = {
            'CODE': {'base': 0x0000, 'limit': 0xFFFF, 'access': 0x9A},
            'DATA': {'base': 0x1000, 'limit': 0xEFFF, 'access': 0x92},
            'STACK': {'base': 0xF000, 'limit': 0xFFFF, 'access': 0x96},
            'VIDEO': {'base': 0xB800, 'limit': 0x7FFF, 'access': 0x92}
        }

    def read_memory(self, segment, offset):
        seg_info = self.segments.get(segment)
        if not seg_info:
            self.handle_memory_fault(0)
            return 0
            
        if offset > seg_info['limit']:
            self.handle_memory_fault(offset)
            return 0
            
        physical_addr = seg_info['base'] + offset
        return self.memory[physical_addr]
        
    def write_memory(self, segment, offset, value):
        seg_info = self.segments.get(segment)
        if not seg_info:
            self.handle_memory_fault(0)
            return
            
        if seg_info['access'] & 0x02 == 0:
            self.handle_memory_fault(offset)
            return 
            
        if offset > seg_info['limit']:
            self.handle_memory_fault(offset)
            return

        physical_addr = seg_info['base'] + offset
        self.memory[physical_addr] = value
        
    def handle_memory_fault(self, address):
        self.push(self.registers['FLAGS'])
        self.push(self.registers['CS'])
        self.push(self.registers['IP'])
        self.registers['IP'] = self.ivt[0x0D]
        
    def allocate_memory(self, size):
        mcb_addr = self.current_mcb
        while mcb_addr < len(self.memory_map):
            if not self.memory_map[mcb_addr]:
                if self.check_free_block(mcb_addr, size):
                    self.set_mcb(mcb_addr, size)
                    return mcb_addr + 16
            mcb_addr += 16 + (self.memory[mcb_addr+1] << 8 | self.memory[mcb_addr])
        return 0xFFFF
        
    def check_free_block(self, addr, size):
        for i in range(addr, addr + size + 16):
            if self.memory_map[i]:
                return False
            return True
            
    def set_mcb(self, addr, size):
        self.memory[addr] = size & 0xFF
        self.memory[addr+1] = (size >> 8) & 0xFF
        self.memory[addr+2] = 0x4D
        for i in range(addr, addr + size + 16):
            self.memory_map[i] = True
            
    def free_memory(self, ptr):
        mcb_addr = ptr - 16
        if self.memory[mcb_addr+2] != 0x4D:
            self.handle_memory_fault(mcb_addr)
            return
            
        size = self.memory[mcb_addr] | (self.memory[mcb_addr+1] << 8)
        for i in range(mcb_addr, mcb_addr + size + 16):
            self.memory_map[i] = False
            
    def load_gdt(self, base, limit):
        self.gdtr['base'] = base
        self.gdtr['limit'] = limit
        for i in range(0, limit+1, 8):
            entry = {
                'base': self.memory[i+2] | (self.memory[i+3] << 8) | (self.memory[i+4] << 16),
                'limit': self.memory[i] | (self.memory[i+1] << 8),
                'access': self.memory[i+5]
            }
            if i//8 >= len(self.gdt):
                self.gdt.append(entry)
            else:
                self.gdt[i//8] = entry
    
    def step_debug(self):
        print("\x1b[2J\x1b[H")
        self.debug_show_registers()
        self.debug_disassemble_text()
        input("Press enter to continue...")

    def debug_show_registers(self):
        print(f"AX: {self.registers['AX']:04X}  BX: {self.registers['BX']:04X}")
        print(f"CX: {self.registers['CX']:04X}  DX: {self.registers['DX']:04X}")
        print(f"IP: {self.registers['IP']:04X}  SP: {self.registers['SP']:04X}")
        print(f"FLAGS: {bin(self.registers['FLAGS'])[2:].zfill(8)}")

    def debug_disassemble_text(self, num_instructions=5):
        ip = self.registers['IP']
        for i in range(num_instructions):
            addr = ip + i
            if addr >= len(self.memory):
                break
            print(f"{addr:04X}: {self.disassemble(addr)}")

    def debug_show_memory(self, start, length):
        for i in range(start, start+length, 16):
            line = f"{i:04X}"
            line += ' '.join(f"{self.memory[j]:02X}" for j in range(i, min(i + 16, start + length)))
            print(line)

    # оптимайзинг йоу
    def enable_jit(self):
        self.execute = numba.jit(self.execute, nopython=True)

    def cache_decoded_instructions(self):
        self.instruction_cache = {}
        for addr in range(len(self.memory)):
            self.instruction_cache[addr] = self.disassemble(addr)

    ##########

    def handle_mul_instruction(self):
        reg_code = self.fetch_instruction()
        reg = self.reg_names[reg_code]
        result = self.registers['AX'] * self.registers[reg]
        self.registers['DX'] = (result >> 16) & 0xFFFF
        self.registers['AX'] = result & 0xFFFF
        self.update_arithmetic_flags(result)

    def handle_div_instruction(self):
        divisor = self.registers[self.reg_names[self.fetch_instruction()]]
        if divisor == 0:
            self.handle_interrupt(0x00)
            return
        dividend = (self.registers['DX'] << 16) | self.registers['AX']
        self.registers['AX'] = dividend // divisor
        var = self.registers['DX'] - dividend % divisor

    def handle_loop_instruction(self):
        count_reg = self.reg_names[self.fetch_instruction()]
        offset = self.fetch_instruction()
        self.registers[count_reg] -= 1
        if self.registers[count_reg] != 0:
            self.registers['IP'] += offset - 2

    def handle_interrupt_flag_instruction(self):
        flag = self.fetch_instruction()
        self.interrupt_enabled = (flag == 0x01)

    def execute_instruction(self):
        pass

    def execute_int(self):
        int_num = self.fetch_instruction()
        self.handle_interrupt(int_num)

    def dump_memory_page(self, page=0):
        print(f"Memory page {page:02X}:")
        for i in range(0, 256, 16):
            line = f"{i:02X}: {' '.join(f'{self.memory[page*256 + j]:02X}' for j in range(i, min(i + 16, 256)))}"
            print(line)
    
    def show_video_output(self):
        print("\x1b[H" + self.vc.get_display_output())

    def update_logic_flags(self):
        self.registers['FLAGS'] = 0b00000000
        value = self.registers['AX']

        if value == 0:
            self.registers['FLAGS'] |= 0b00000001 # нуль
        if value & 0x8000:
            self.registers['FLAGS'] |= 0b00000010 # сигна

    def update_shift_flags(self, count):
        self.registers['FLAGS'] = 0b00000000
        value = self.registers['AX']

        if value == 0:
            self.registers['FLAGS'] |= 0b00000001  # нуль
        if value & 0x8000:
            self.registers['FLAGS'] |= 0b00000010  # сигна

        if count > 0:
            mask = 0x8000 >> (16 - count)
            if (self.registers['AX'] << (count - 1)) & 0x8000:
                self.registers['FLAGS'] |= 0b00000100

    def poll_keyboard(self):
        import sys
        from select import select
        if select([sys.stdin], [], [], 0)[0]:
            self.add_key_input(sys.stdin.read(1))

    def shutdown(self):
        print("\x1b[0m\x1b[?25h", end='')
        raise SystemExit

    def execute(self):
        try:
            while True:
                if self.registers['IP'] in self.breakpoints and self.debug_mode:
                    self.step_debug()

                self.vc.show_video_output()

                if self.registers['IP'] >= len(self.memory):
                    self.handle_interrupt(0x00)
                    continue
            
                opcode = self.fetch_instruction()

                try:
                    with open("cpu.log", "a") as log:
                        log.write(f"IP: {self.registers['IP']:04X} OP: {opcode:02X} AX={self.registers['AX']:04X}\n")
                except Exception as log_error:
                    print(f"\x1b[31mLog error: {log_error}\x1b[0m")
                
                if opcode == 0x01:
                    reg_code = self.fetch_instruction()
                    value_high = self.fetch_instruction()
                    value_low = self.fetch_instruction()
                    value = (value_high << 8) | value_low
                    reg_name = ['AX', 'BX', 'CX', 'DX'][reg_code]
                    self.registers[reg_name] = value
                elif opcode == 0x02:
                    reg1_code = self.fetch_instruction()
                    reg2_code = self.fetch_instruction()
                    reg1 = ['AX', 'BX', 'CX', 'DX'][reg1_code]
                    reg2 = ['AX', 'BX', 'CX', 'DX'][reg2_code]

                    result = self.registers[reg1] + self.registers[reg2]
                    self.registers[reg1] = result & 0xFFFF

                    # обнова флагов
                    self.registers['FLAGS'] = 0b00000000
                    if result > 0xFFFF:
                        self.registers['FLAGS'] |= 0b00000010 # флаг переноса
                    if self.registers[reg1] == 0:
                        self.registers['FLAGS'] |= 0b00000001 # нулевой результат
                elif opcode == 0x03:
                    addr_high = self.fetch_instruction()
                    addr_low = self.fetch_instruction()
                    self.registers['IP'] = (addr_high << 8) | addr_low
                elif opcode == 0x04:
                    # sub
                    reg1_code = self.fetch_instruction()
                    reg2_code = self.fetch_instruction()
                    reg1 = self.reg_names[reg1_code]
                    reg2 = self.reg_names[reg2_code]
                    result = self.registers[reg1] - self.registers[reg2]
                    self.registers[reg1] = result & 0xFFFF
                    self.update_arithmetic_flags(result)
                elif opcode == 0x05:
                    # and
                    reg1_code = self.fetch_instruction()
                    reg2_code = self.fetch_instruction()
                    reg1 = self.reg_names[reg1_code]
                    reg2 = self.reg_names[reg2_code]
                    self.registers[reg1] &= self.registers[reg2]
                    self.update_logic_flags()
                elif opcode == 0x06:
                    # shl
                    reg_code = self.fetch_instruction()
                    count = self.fetch_instruction()
                    reg = self.reg_names[reg_code]
                    self.registers[reg] = (self.registers[reg] << count) & 0xFF
                    self.update_shift_flags(count)
                elif opcode == 0x07:
                    # OR
                    reg1_code = self.fetch_instruction()
                    reg2_code = self.fetch_instruction()
                    reg1 = self.reg_names[reg1_code]
                    reg2 = self.reg_names[reg2_code]
                    self.registers[reg1] |= self.registers[reg2]
                    self.update_logic_flags()
                elif opcode == 0x08:
                    # XOR
                    reg1_code = self.fetch_instruction()
                    reg2_code = self.fetch_instruction()
                    reg1 = self.reg_names[reg1_code]
                    reg2 = self.reg_names[reg2_code]
                    self.registers[reg1] ^= self.registers[reg2]
                    self.update_logic_flags()
                elif opcode == 0x09:
                    # NOT
                    reg_code = self.fetch_instruction()
                    reg = self.reg_names[reg_code]
                    self.registers[reg] = ~self.registers[reg] & 0xFFFF
                    self.update_logic_flags()
                elif opcode == 0x10:
                    # MUL
                    self.handle_mul_instruction()
                elif opcode == 0x11:
                    # DIV
                    self.handle_div_instruction()
                elif opcode == 0x12:
                    # LOOP
                    self.handle_loop_instruction()
                elif opcode == 0x13:
                    # STI/CLI
                    self.handle_interrupt_flag_instruction()
                elif opcode == 0x0A:
                    # CMP
                    reg1_code = self.fetch_instruction()
                    reg2_code = self.fetch_instruction()
                    reg1 = self.reg_names[reg1_code]
                    reg2 = self.reg_names[reg2_code]
                    result = self.registers[reg1] - self.registers[reg2]
                    self.update_arithmetic_flags(result)
                elif opcode == 0x0B:
                    # JE (jump если есть =)
                    addr_high = self.fetch_instruction()
                    addr_low = self.fetch_instruction()
                    if self.registers['FLAGS'] & 0b0000001:
                        self.registers['IP'] = (addr_high << 8) | addr_low
                elif opcode == 0x0C:
                    # CALL
                    addr_high = self.fetch_instruction()
                    addr_low = self.fetch_instruction()
                    self.push(self.registers['IP'])
                    self.registers['IP'] = (addr_high >> 8) | addr_low
                elif opcode == 0x0D:
                    # RET
                    self.registers['IP'] = self.pop()
                elif opcode == 0x0E:
                    # INC
                    reg_code = self.fetch_instruction()
                    reg = self.reg_names[reg_code]
                    self.registers[reg] = (self.registers[reg] + 1) & 0xFFFF
                    self.update_arithmetic_flags(self.registers[reg])
                elif opcode == 0x0F:
                    # DEC
                    reg_code = self.fetch_instruction()
                    reg = self.reg_names[reg_code]
                    self.registers[reg] = (self.registers[reg] - 1) & 0xFFFF
                    self.update_arithmetic_flags(self.registers[reg])
                elif opcode == 0x50:  # PUSH AX
                    self.push(self.registers['AX'])
                elif opcode == 0x58:  # POP AX
                    self.registers['AX'] = self.pop()
                elif opcode == 0xE4:  # IN AL, port
                    port = self.fetch_instruction()
                    self.registers['AX'] = self.ports[port]
                elif opcode == 0xE6:  # OUT port, AL
                    port = self.fetch_instruction()
                    self.ports[port] = self.registers['AX'] & 0xFF
                elif opcode == 0xA4:  # MOVSB
                    src = (self.registers['DS'] << 4) + self.registers['SI']
                    dest = (self.registers['ES'] << 4) + self.registers['DI']
                    self.memory[dest] = self.memory[src]
                    self.registers['SI'] += -1 if self.direction_flag else 1
                    self.registers['DI'] += -1 if self.direction_flag else 1
                elif opcode == 0xFC:  # CLD (Clear Direction Flag)
                    self.direction_flag = False
                elif opcode == 0xFD:  # STD (Set Direction Flag)
                    self.direction_flag = True
                elif opcode == 0x14:
                    # JNE
                    addr_high = self.fetch_instruction()
                    addr_low = self.fetch_instruction()
                    if not (self.registers['FLAGS'] & 0b00000001):
                        self.registers['IP'] = (addr_high << 8) | addr_low
                elif opcode == 0x15:
                    # JG
                    addr_high = self.fetch_instruction()
                    addr_low = self.fetch_instruction()
                    sf = (self.registers['FLAGS'] & 0b00000010) >> 1
                    of = (self.registers['FLAGS'] & 0b00001000) >> 3
                    zf = self.registers['FLAGS'] & 0b00000001
                    if not zf and (zf == of):
                        self.registers['IP'] = (addr_high << 8) | addr_low
                elif opcode == 0x17:
                    # TEST reg1, reg2
                    reg1_code = self.fetch_instruction()
                    reg2_code = self.fetch_instruction()
                    reg1 = self.reg_names[reg1_code]
                    reg2 = self.reg_names[reg2_code]
                    result = self.registers[reg1] & self.registers[reg2]
                    self.update_logic_flags(result)
                elif opcode == 0x9C:
                    # PUSHF
                    self.push(self.registers['FLAGS'])
                elif opcode == 0x9D:
                    # POPF
                    self.registers['FLAGS'] = self.pop() & 0xFF
                elif opcode == 0x8D:
                    # LEA reg, [offset]
                    reg_code = self.fetch_instruction()
                    offset_high = self.fetch_instruction()
                    offset_low = self.fetch_instruction()
                    self.registers[self.reg_names[reg_code]] = (offset_high << 8) | offset_low
                elif opcode in {0x53, 0x51, 0x52}:
                    # PUSH BX/CX/DX
                    reg_map = {0x53: 'BX', 0x51: 'CX', 0x52: 'DX'}
                    self.push(self.registers[reg_map[opcode]])
                    
                elif opcode in {0x5B, 0x59, 0x5A}:
                    # POP BX/CX/DX
                    reg_map = {0x5B: 'BX', 0x59: 'CX', 0x5A: 'DX'}
                    self.registers[reg_map[opcode]] = self.pop()
                elif opcode == 0x1B:
                    # JMP short
                    offset = self.fetch_instruction()
                    self.registers['IP'] += offset - 2
                elif opcode == 0x1C:
                    # JC (Jump if Carry)                
                    addr_high = self.fetch_instruction()
                    addr_low = self.fetch_instruction()
                    if self.registers['FLAGS'] & 0b00000010:
                        self.registers['IP'] = (addr_high << 8) | addr_low
                elif opcode == 0x1D:
                    # JNC (Jump if Not Carry)
                    addr_high = self.fetch_instruction()
                    addr_low = self.fetch_instruction()
                    if not (self.registers['FLAGS'] & 0b00000010):
                        self.registers['IP'] = (addr_high << 8) | addr_low
                elif opcode == 0x1E:
                    # MOV [BX], AX
                    address = self.registers['BX']
                    self.memory[address] = (self.registers['AX'] >> 8) & 0xFF
                    self.memory[address + 1] = self.registers['AX'] & 0xFF
                elif opcode == 0x1F:
                    # MOV AX, [BX]
                    address = self.registers['BX']
                    self.registers['AX'] = (self.memory[address] << 8) | self.memory[address + 1]
                elif opcode == 0x20:
                    # ADC (Add with Carry)                
                    reg1_code = self.fetch_instruction()
                    reg2_code = self.fetch_instruction()
                    reg1 = self.reg_names[reg1_code]
                    reg2 = self.reg_names[reg2_code]
                    carry = (self.registers['FLAGS'] & 0b00000010) >> 1
                    result = self.registers[reg1] + self.registers[reg2] + carry
                    self.registers[reg1] = result & 0xFFFF
                    self.update_arithmetic_flags(result)
                elif opcode == 0x21:
                    # SBB (Subtract with Borrow)
                    reg1_code = self.fetch_instruction()
                    reg2_code = self.fetch_instruction()
                    reg1 = self.reg_names[reg1_code]
                    reg2 = self.reg_names[reg2_code]
                    borrow = (self.registers['FLAGS'] & 0b00000010) >> 1
                    result = self.registers[reg1] - self.registers[reg2] - borrow
                    self.registers[reg1] = result & 0xFFFF
                    self.update_arithmetic_flags(result)
                elif opcode == 0x22:
                    # CLC (Clear Carry Flag)
                    self.registers['FLAGS'] &= ~0b00000010
                elif opcode == 0x23:
                    # STC (Set Carry Flag)
                    self.registers['FLAGS'] |= 0b00000010
                elif opcode == 0x24:
                    # LODSB (Load String Byte)
                    self.registers['AX'] = self.memory[(self.registers['DS'] << 4) + self.registers['SI']]
                    self.registers['SI'] += 1 if not self.direction_flag else -1
                elif opcode == 0x25:
                    # STOSB (Store String Byte)
                    self.memory[(self.registers['ES'] << 4) + self.registers['DI']] = self.registers['AX'] & 0xFF
                    self.registers['DI'] += 1 if not self.direction_flag else -1
                elif opcode == 0x26:
                    # PUSHA (Push All Registers)
                    sp = self.registers['SP']
                    self.push(self.registers['AX'])
                    self.push(self.registers['CX'])
                    self.push(self.registers['DX'])
                    self.push(self.registers['BX'])
                    self.push(sp)
                    self.push(self.registers['BP'])
                    self.push(self.registers['SI'])
                    self.push(self.registers['DI'])
                elif opcode == 0x27:
                    # POPA (Pop All Registers)
                    self.registers['DI'] = self.pop()
                    self.registers['SI'] = self.pop()
                    self.registers['BP'] = self.pop()
                    self.pop()  # Skip SP
                    self.registers['BX'] = self.pop()
                    self.registers['DX'] = self.pop()
                    self.registers['CX'] = self.pop()
                    self.registers['AX'] = self.pop()
                elif opcode == 0x28:
                    # ROL (Rotate Left)
                    reg_code = self.fetch_instruction()
                    count = self.fetch_instruction()
                    reg = self.reg_names[reg_code]
                    value = self.registers[reg]
                    for _ in range(count):
                        bit = (value >> 15) & 1
                        value = ((value << 1) | bit) & 0xFFFF
                    self.registers[reg] = value
                    self.update_shift_flags(count)
                elif opcode == 0x29:
                    # ROR (Rotate Right)
                    reg_code = self.fetch_instruction()
                    count = self.fetch_instruction()
                    reg = self.reg_names[reg_code]
                    value = self.registers[reg]
                    for _ in range(count):
                        bit = value & 1
                        value = (value >> 1) | (bit << 15)
                    self.registers[reg] = value
                    self.update_shift_flags(count)
                # Обработка префиксов
                if opcode == 0xF3:  # REP префикс
                    self.rep_prefix = True
                    opcode = self.fetch_instruction()
                
                if opcode == 0xA4:  # MOVSB
                    count = self.registers['CX'] if self.rep_prefix else 1
                    for _ in range(count):
                        src = (self.registers['DS'] << 4) + self.registers['SI']
                        dest = (self.registers['ES'] << 4) + self.registers['DI']
                        self.memory[dest] = self.memory[src]
                        self.registers['SI'] += -1 if self.direction_flag else 1
                        self.registers['DI'] += -1 if self.direction_flag else 1
                        if self.rep_prefix: 
                            self.registers['CX'] -= 1
                            if self.registers['CX'] == 0: break
                    self.rep_prefix = False

                elif opcode == 0xA6:  # CMPSB
                    count = self.registers['CX'] if self.rep_prefix else 1
                    for _ in range(count):
                        src = (self.registers['DS'] << 4) + self.registers['SI']
                        dest = (self.registers['ES'] << 4) + self.registers['DI']
                        res = self.memory[src] - self.memory[dest]
                        self.update_arithmetic_flags(res)
                        self.registers['SI'] += -1 if self.direction_flag else 1
                        self.registers['DI'] += -1 if self.direction_flag else 1
                        if self.rep_prefix: 
                            self.registers['CX'] -= 1
                            if self.registers['CX'] == 0 or res != 0: break
                    self.rep_prefix = False

                elif opcode == 0xAE:  # SCASB
                    count = self.registers['CX'] if self.rep_prefix else 1
                    for _ in range(count):
                        addr = (self.registers['ES'] << 4) + self.registers['DI']
                        res = (self.registers['AX'] & 0xFF) - self.memory[addr]
                        self.update_arithmetic_flags(res)
                        self.registers['DI'] += -1 if self.direction_flag else 1
                        if self.rep_prefix: 
                            self.registers['CX'] -= 1
                            if self.registers['CX'] == 0 or res == 0: break
                    self.rep_prefix = False
                elif opcode == 0x54:  # PUSH SP
                    self.push(self.registers['SP'])
                elif opcode == 0x55:  # PUSH BP
                    self.push(self.registers['BP'])
                elif opcode == 0x56:  # PUSH SI
                    self.push(self.registers['SI'])
                elif opcode == 0x57:  # PUSH DI
                    self.push(self.registers['DI'])
                elif opcode == 0x06:  # PUSH ES
                    self.push(self.registers['ES'])
                elif opcode == 0x0E:  # PUSH CS
                    self.push(self.registers['CS'])
                elif opcode == 0x16:  # PUSH SS
                    self.push(self.registers['SS'])
                elif opcode == 0x1E:  # PUSH DS
                    self.push(self.registers['DS'])
                    
                elif opcode == 0x5C:  # POP SP
                    self.registers['SP'] = self.pop()
                elif opcode == 0x5D:  # POP BP
                    self.registers['BP'] = self.pop()
                elif opcode == 0x5E:  # POP SI
                    self.registers['SI'] = self.pop()
                elif opcode == 0x5F:  # POP DI
                    self.registers['DI'] = self.pop()
                elif opcode == 0x07:  # POP ES
                    self.registers['ES'] = self.pop()
                elif opcode == 0x0F:  # POP CS
                    self.registers['CS'] = self.pop()
                elif opcode == 0x17:  # POP SS
                    self.registers['SS'] = self.pop()
                elif opcode == 0x1F:  # POP DS
                    self.registers['DS'] = self.pop()

                # Special case for flags
                elif opcode == 0x9C:  # PUSHF
                    self.push(self.registers['FLAGS'])
                elif opcode == 0x9D:  # POPF
                    self.registers['FLAGS'] = self.pop() & 0xFF
                elif opcode == 0x70:
                    cmd = self.fetch_instruction()
                    if cmd == 0x01:
                        # BLIT
                        src_addr = (self.registers['DS'] << 4) + self.registers['SI']
                        dest_x = self.registers['DX'] & 0xFF
                        dest_y = (self.registers['DX'] >> 8) & 0xFF
                        width = self.registers['CX'] & 0xFF
                        height = (self.registers['CX'] >> 8) & 0xFF
                        self.vc.blit(src_addr, dest_x, dest_y, width, height)
                elif opcode == 0x71:
                    # VECTOR_OP 
                    op_type = self.fetch_instruction()
                    vector_len = self.registers['CX']
                    src = (self.registers['DS'] << 4) + self.registers['SI']
                    dest = (self.registers['ES'] << 4) + self.registers['DI']
                    
                    for i in range(vector_len):
                        val = self.memory[src + i]
                        if op_type == 0x01:
                            val += self.memory[dest + i]
                        elif op_type == 0x02:
                            val *= self.memory[dest + i]
                        self.memory[dest + i] = val & 0xFF
                elif opcode == 0xB8:
                    low = self.fetch_instruction()
                    high = self.fetch_instruction()
                    self.registers['AX'] = (high << 8) | low
                elif opcode == 0xCD:
                    # INT (обработчик)
                    int_num = self.fetch_instruction()
                    log.write(f"INT {int_num:02X} called\n")
                    self.handle_interrupt(int_num)
                elif opcode == 0xFF:
                    break

        except Exception as e:
            print(f"\x1b[1;31mExecution halted: {str(e)}\x1b[0m")
            self.registers['IP'] = 0
            self.update_flags()
                          
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Petysh Terminal Emulator')
    parser.add_argument('--disk', help="Файл образа диска")
    parser.add_argument('--programs', default="programs/", help="Директория с программами")
    args = parser.parse_args()

    cpu = PetyshCore16()
    cpu.programs_dir = args.programs
    
    # Создаем директорию программ если ее нет
    os.makedirs(args.programs, exist_ok=True)
    
    if args.disk:
        try:
            with open(args.disk, 'rb') as f:
                # Загружаем образ в "дисковую" память
                disk_content = f.read()
                sector_size = 512
                for i in range(0, len(disk_content), sector_size):
                    cpu.disk_data[i//sector_size] = disk_content[i:i+sector_size]
        except FileNotFoundError:
            print(f"\x1b[31mError: Disk image '{args.disk}' not found\x1b[0m")
            sys.exit(1)
        
        # Эмулируем загрузку через BIOS
        cpu.registers['DL'] = 0x80  # Номер диска
        cpu.handle_interrupt(0x13)  # Чтение диска
        cpu.registers['CS'] = 0x0000
        cpu.registers['IP'] = 0x8000

    cpu.terminal_loop()
