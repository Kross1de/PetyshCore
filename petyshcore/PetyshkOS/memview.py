def hexdump(memory, address, length=128):
    for i in range(0, length, 16):
        chunk = memory[address+i:address+i+16]
        print(f"{address+i:04X}: {' '.join(f'{b:02X}' for b in chunk)}")