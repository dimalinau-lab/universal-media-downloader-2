---
name: Universal Media Downloader
description: Fluent Design media downloader and streamer console for Windows
colors:
  primary: "#005fb8"
  primary-hover: "#106ebe"
  primary-pressed: "#005a9e"
  dark-bg: "#202020"
  dark-surface: "#272727"
  dark-border: "rgba(255, 255, 255, 0.08)"
  dark-border-hover: "rgba(255, 255, 255, 0.16)"
  dark-text-primary: "#ffffff"
  dark-text-secondary: "#a0a0a0"
  light-bg: "#f3f3f3"
  light-surface: "#ffffff"
  light-border: "rgba(0, 0, 0, 0.06)"
  light-border-hover: "rgba(0, 0, 0, 0.16)"
  light-text-primary: "#000000"
  light-text-secondary: "#606060"
  success: "#10b981"
  warning: "#f59e0b"
  danger: "#ef4444"
typography:
  title:
    fontFamily: "Segoe UI Variable, Segoe UI, Roboto, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1.3
  body:
    fontFamily: "Segoe UI Variable, Segoe UI, Roboto, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.4
  label:
    fontFamily: "Segoe UI Variable, Segoe UI, Roboto, sans-serif"
    fontSize: "12px"
    fontWeight: 500
    lineHeight: 1.2
  mono:
    fontFamily: "monospace, sans-serif"
    fontSize: "13px"
    fontWeight: 600
    lineHeight: 1.3
rounded:
  sm: "4px"
  md: "6px"
  lg: "8px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "32px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-secondary:
    backgroundColor: "rgba(255, 255, 255, 0.06)"
    textColor: "{colors.dark-text-primary}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "32px"
  card-default:
    backgroundColor: "{colors.dark-surface}"
    rounded: "{rounded.lg}"
    padding: "16px"
---

# Design System: Universal Media Downloader

## Overview

**Creative North Star: "Fluent Precision Console"**

Universal Media Downloader спроектирован как высокоточная нативная десктопная консоль в визуальном стиле Windows 11 Fluent Design. Интерфейс подчинен принципам строгости, бесшумности и максимальной функциональной информативности: пользователь видит текущее состояние очереди задач, битрейт, скорость и прогресс без визуальной перегрузки и отвлекающих анимаций.

Визуальный мир строится вокруг контраста темных поверхностей, полупрозрачных разделителей и единственного акцентного синего цвета Windows (`#005fb8`), направляющего внимание исключительно на ключевые действия. Все элементы обладают строгой геометрией и нативной предсказуемостью.

**Key Characteristics:**
- Нативный Windows 11 Fluent Design (Mica/Acrylic эстетика, скругления 6–8px).
- Тональное наслоение поверхностей вместо рассеянных теней.
- Точечное применение акцентного цвета (не более 10% площади экрана).
- Строгая 4/8px сетка и устойчивая типографика Segoe UI Variable.

## Colors

Палитра базируется на нейтральных оттенках Windows Dark Mode с каноническим акцентным цветом Fluent Blue.

### Primary
- **Fluent Blue** (`#005fb8` / hover `#106ebe` / pressed `#005a9e`): Основной акцент для главных кнопок действий («Скачать», запуск очереди, подтверждение).

### Neutral
- **Canvas Base** (Dark `#202020` / Light `#f3f3f3`): Главный фоновый холст приложения и диалоговых окон.
- **Card Surface** (Dark `#272727` / Light `#ffffff`): Фоновый слой карточек очереди, тулбаров и сгруппированных настроек.
- **Micro Border** (Dark `rgba(255, 255, 255, 0.08)` / Light `rgba(0, 0, 0, 0.06)`): Тонкие границы толщиной 1px, формирующие геометрию карточек и панелей без тяжелых теней.
- **Text Primary** (Dark `#ffffff` / Light `#000000`): Высококонтрастный текст названий роликов, секций и значений.
- **Text Muted** (Dark `#a0a0a0` / Light `#606060`): Второстепенный текст ссылок, подсказок и технических параметров.

### Semantic
- **Success Emerald** (`#10b981` / Light `#107c41`): Завершенные загрузки, успешное подключение Telegram-бота.
- **Warning Amber** (`#f59e0b` / Light `#b45309`): Пауза, ожидание фрагментов, предупреждения сети.
- **Danger Crimson** (`#ef4444` / Light `#dc2626`): Ошибки загрузки, недоступность потока, отмена.

### Named Rules
**The Focused Accent Rule.** Акцентный синий цвет `#005fb8` зарезервирован строго для первичных действий и индикатора прогресса. Второстепенные кнопки и панели используют полупрозрачные нейтральные заливки.

## Typography

**Display/Body Font:** `Segoe UI Variable`, `Segoe UI`, `Roboto`, sans-serif
**Mono Font:** `monospace, sans-serif`

**Character:** Чистая, четкая системная типографика Windows с безупречной читаемостью на High-DPI экранах.

### Hierarchy
- **Title** (SemiBold 600, 15px, line-height 1.3): Названия медиафайлов в очереди, заголовки диалогов и настроек.
- **Body** (Regular 400, 14px, line-height 1.4): Основной текст, описания, элементы списков и таблиц.
- **Label** (Medium 500, 12px, line-height 1.2): Подписи параметров, серий, статусов очереди и тултипов.
- **Mono** (SemiBold 600, 13px, line-height 1.3): Технические параметры потоков, битрейты, разрешения (1080p, 4K, 320 kbps).

## Layout

- **Сетка:** 4px и 8px базовый пространственный шаг.
- **Внутренние отступы карточек:** 16px для рабочих элементов, 24px для пустых состояний (EmptyCard).
- **Высота управляющих элементов:** Стандартизирована до 32px для кнопок действий и полей ввода.
- **Компоновка:** Боковая панель навигации фиксированной ширины, центральная гибкая область карточек очереди с независимой плавной прокруткой.

## Elevation & Depth

Система использует **тональное плоское наслоение (Tonal Layering)**. Физические тени с размытием исключены, чтобы сохранить чистоту и нативную производительность интерфейса.

Глубина формируется тремя уровнями:
1. Базовый холст окна: `#202020`
2. Поверхность карточек и тулбаров: `#272727` + микро-бордер `rgba(255, 255, 255, 0.08)`
3. Всплывающие тултипы и выпадающие списки: `#2b2b2b` + граница `rgba(255, 255, 255, 0.14)`

### Named Rules
**The Zero-Drop-Shadow Rule.** Никаких искусственных размытых теней `box-shadow` в покое. Разделение слоев достигается исключительно градацией цвета фона и 1px полупрозрачными рамками.

## Shapes

- **Контейнеры и карточки задач:** `border-radius: 8px` — нативный Windows 11 радиус.
- **Кнопки, инпуты, селекторы:** `border-radius: 6px`.
- **Прогресс-бары:** `border-radius: 4px`, высота 6px.
- **Бейджи версий и статусов:** `border-radius: 6px`, padding `2px 8px`.

## Components

### Buttons
- **Primary Action:** Фон `#005fb8`, текст `#ffffff`, радиус `6px`, высота `32px`. При наведении `#106ebe`, при нажатии `#005a9e`.
- **Secondary Action:** Фон `rgba(255, 255, 255, 0.06)`, текст `#ffffff`, тонкая рамка 1px, радиус `6px`. При наведении `rgba(255, 255, 255, 0.1)`.
- **Navigation Button:** Прозрачный фон, выравнивание влево, отступы `8px 12px`, мягкий ховер `rgba(255, 255, 255, 0.06)`.

### Cards & Download Items
- Фон `#272727`, граница `1px solid rgba(255, 255, 255, 0.08)`, радиус `8px`. При наведении граница усиливается до `rgba(255, 255, 255, 0.16)`.
- Внутри карточки: слева превью/логотип платформы, по центру название и статус, справа выпадающие меню качества и кнопки управления.

### Progress Bars
- Подложка `rgba(255, 255, 255, 0.1)`, активный чанк `#005fb8`, радиус `4px`, компактная высота `6px`.

## Do's and Don'ts

### Do:
- **Do** использовать только нативную палитру Fluent Design (`#005fb8`, `#202020`, `#272727`).
- **Do** выдерживать радиус карточек строго 8px, а кнопок и полей ввода — 6px.
- **Do** разделять блоки 1px микро-бордерами `rgba(255, 255, 255, 0.08)` вместо цветных или толстых линий.
- **Do** использовать системный шрифт `Segoe UI Variable`.

### Don't:
- **Don't** добавлять ядовитые градиенты, неоновые обводки или произвольные цвета кнопок.
- **Don't** использовать тяжелые тени с большим радиусом размытия.
- **Don't** смешивать разные радиусы скругления в соседних элементах одного уровня.
- **Don't** применять декоративные медленные анимации (>250 мс), задерживающие отклик интерфейса.
