	;; PetyshkOS - Operation system for processor 'PetyshCore'
	;; Version: 0.1 (Alpha)
	;; (c) 2025 Syncas

	org 0x8000 		; boot address
	bits 16			; 16-BIT

start:
	cli			; prohibiting interruptions
	xor ax, ax
	mov ds, ax
	mov es, ax
	mov ss, ax
	mov sp, 0x7C00

	mov ax, 0x0003
	int 0x10

	mov si, os_name
	call print_string

	;; os main loop
main_loop:
	mov si, prompt
	call print_string
	call read_input
	jmp main_loop

	;; --------------------
	;; Print string to display
	;; Enter: SI - String address
	;; --------------------
print_string:
	lodsb
	or al, al
	jz .done
	mov ah, 0x0E
	int 0x10
	jmp print_string
	.done:
	ret

	;; -------------------
	;; Read keyboard input
	;; -------------------
read_input:
	xor bx, bx
	.input_loop:
	mov ax, 0x00
	int 0x16

	cmp al, 0x0D
	je .process_cmd

	cmp al, 0x08
	je .backspace

	mov ah, 0x0E
	int 0x10
	mov [input_buffer+bx], al
	inc bx
	jmp .input_loop

	.backspace:
	test bx, bx
	jz .input_loop
	dec bx
	mov ah, 0x0E
	mov al, 0x08
	int 0x10
	mov al, ' '
	int 0x10
	mov al, 0x08
	int 0x10
	jmp .input_loop

	.process_cmd:
	mov byte [input_buffer+bx], 0
	mov si, input_buffer
	call execute_command
	ret

	;; ------------------
	;; Command processing
	;; Enter: SI - address command
	;; ------------------
execute_command:
	mov di, cmd_help
	call strcmp
	jc .help

	mov di , cmd_cls
	call strcmp
	jc .cls

	mov si, unknown_cmd
	call print_string
	ret

	.help:
	mov si, help_text
	call print_string
	ret

	.cls:
	mov ax, 0x0003
	int 0x10
	ret

	;-----------------------------
	; String comparison
	; Input: SI - string1, DI - string2
	; Output: CF=1 if they match
				;-----------------------------
strcmp:
	.loop:
	mov al, [si]
	cmp al, [di]
	jne .not_equal
	test al, al
	jz .equal
	inc si
	inc di
	jmp .loop
	.not_equal:
	clc
	ret
	.equal:
	stc
	ret

	;; -------------
	;; OS data
	;; -------------
os_name     db 13,10,'PetyshkOS v0.1',13,10
            db 'Type "help" for commands',13,10,0
prompt      db 13,10,'> ',0
cmd_help    db 'help',0
cmd_cls     db 'cls',0
help_text   db 13,10,'Available commands:',13,10
            db 'help - Show this help',13,10
            db 'cls  - Clear screen',13,10,0
unknown_cmd db 13,10,'Unknown command',13,10,0
input_buffer times 64 db 0

times 512-($-$$) db 0
