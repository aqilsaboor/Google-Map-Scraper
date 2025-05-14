import requests

cities = [
    "Linz",
    "Salzburg",
    "Innsbruck",
    "Klagenfurt",
    "Wels",
    "Villach",
    "Sankt Pölten",
    "Kitzbühel",
    "Bad Ischl",
    "Feldkirch",
    "Zell am See",
    "Saalbach-Hinterglemm",
    "Leogang",
    "Korneuburg",
    "Baden",
    "Eisenstadt",
    "St. Johann im Pongau",
    "Mistelbach",
    "Bruck an der Mur",
    "St. Veit an der Glan",
    "Amstetten",
    "Tulln an der Donau",
    "Feldbach",
    "Ried im Innkreis",
    "Gmunden",
    "Schwechat",
    "Krems an der Donau",
    "Hallein"
]


for city in cities:
    respone= requests.get(f"http://192.168.1.39:5001/scrape?search_query=salon in {city}, austria")
    print(respone) 