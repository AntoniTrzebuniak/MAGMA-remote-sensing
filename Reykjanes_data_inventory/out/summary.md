# Dostępność danych, ROI Reykjanes
Filtry: pokrycie ROI >= 0.5, chmury <= 0.3 (nocne bez filtra chmur)

## Przeloty na rok
```
datetime_utc  2020  2021  2022  2023  2024  2025  2026
sensor                                                
EnMAP dzień      0     0     4    25    25     3     1
EnMAP noc        0     0    14    23    43    13     0
L8 dzień         2     9     9    11     9     9     8
L8 noc           6    55    58    61    45    67    53
L9 dzień         0     0     8     8    11     8     6
L9 noc           0     0    49    56    43    65    55
```

## Sceny hiperspektralne vs najbliższy Landsat
- EnMAP dzień: 58 scen | Landsat dzień <= 6 h: 8, <= 24 h: 10, <= 72 h: 21 | noc w ±7 dni: 55
- EnMAP noc: 93 scen | Landsat noc <= 6 h: 37, <= 24 h: 49, <= 72 h: 90

## Landsat noc
- przelotów: 613, słońce < 0°: 490, z czystą sceną dzienną w ±48 h: 181
```
datetime_utc  1   2   3   4   5   6   7   8   9   10  11  12
datetime_utc                                                
2020           0   0   0   0   0   0   0   0   2   2   1   1
2021           2   1   3   5   5   6   6   6   6   4   5   6
2022           6   6   2   5   9  12  12  11   9  11  12  12
2023          12   9  12   5   6  10  11  12  11  11   8  10
2024          11  12  10  10   7   0   0   6   2   9   9  12
2025          12  11  10  11  11  12  12  11  10   8  12  12
2026          12   9  11  11  12  10  11  12  11   9   0   0
```