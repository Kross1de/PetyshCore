import os
def create_disk_image(files, output="disk.img"):
    with open(output, "wb") as f:
        # Создаем пустой образ размером 1440 KB (стандартная дискета)
        f.seek(1474560 - 1)
        f.write(b'\x00')
        f.seek(0)
        
        # Записываем загрузочный сектор
        if 0 in files:
            f.write(files[0].ljust(512, b'\x00'))
        else:
            f.write(b'\x00'*512)
        
        # Записываем остальные секторы
        for sector in range(1, 2880):  # 1440 KB / 512 B = 2880 секторов
            if sector in files:
                f.write(files[sector].ljust(512, b'\x00'))
            else:
                f.write(b'\x00'*512)

# Пример использования через командную строку:
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--files', nargs='+', help="Файлы в формате filename:sector")
    parser.add_argument('-o', '--output', default="disk.img")
    args = parser.parse_args()

    files_dict = {}
    for entry in args.files:
        filename, sector = entry.split(':')
        with open(filename, 'rb') as fl:
            files_dict[int(sector)] = fl.read()
    
    create_disk_image(files_dict, args.output)
    print(f"Образ {args.output} создан, размер: {os.path.getsize(args.output)//1024} KB")