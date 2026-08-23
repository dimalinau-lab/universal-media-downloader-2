import time
from selenium import webdriver
from selenium.webdriver.edge.service import Service
from selenium.webdriver.edge.options import Options
from webdriver_manager.microsoft import EdgeChromiumDriverManager

URL = "https://vi3000.top/?card=1317149&media=movie&source=cub"

print("Запускаем браузер...")
options = Options()
options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
driver = webdriver.Edge(service=Service(EdgeChromiumDriverManager().install()), options=options)

try:
    driver.get(URL)
    print("\n=======================================================")
    print("Браузер открыт! Проходи всё шаг за шагом.")
    print("В любой момент нажми ENTER в этой консоли, и я сделаю слепок кода.")
    print("=======================================================\n")

    count = 1
    while True:
        command = input(f"Нажми ENTER для создания слепка №{count} (или введи 'q' для выхода): ")
        if command.lower() == 'q':
            break

        filename = f"lampa_step_{count}.html"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(driver.page_source)

        print(f"[УСПЕХ] Слепок сохранен в файл: {filename}\n")
        count += 1

except Exception as e:
    print(f"Ошибка: {e}")
finally:
    driver.quit()
    print("Браузер закрыт.")