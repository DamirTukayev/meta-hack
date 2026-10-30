"""The same ten requests in six languages, for the parsing evaluation: does the model read a request written in Russian, Spanish, French,
German or Portuguese as well as one in English?

The expected constraints are the same for every language. Written by the project author, so they measure robustness to language, not to the wild.
"""

from __future__ import annotations

EXPECTED: list[dict] = [
    dict(n_orders=30, n_vehicles=3, deadline="18:00", avoid={"industrial"}),
    dict(n_orders=12, n_vehicles=1, deadline="12:00"),
    dict(n_orders=20, n_vehicles=2, deadline="17:00", avoid={"residential"}),
    dict(n_orders=28, n_vehicles=4, deadline="15:15", avoid={"flooded"}),
    dict(n_orders=15, shift_start="07:00", deadline="14:00", avoid={"park_forest"}),
    dict(n_orders=40, n_vehicles=4, deadline="17:45"),
    dict(n_orders=10, n_vehicles=2, service_minutes=5, deadline="11:00"),
    dict(n_orders=50, n_vehicles=5),
    dict(n_orders=18, n_vehicles=3, deadline="13:45", avoid={"commercial"}),
    dict(n_orders=6, n_vehicles=1, shift_start="08:30", deadline="11:00"),
]

TEXTS: dict[str, list[str]] = {
    "English": [
        "30 orders, 3 trucks, by 18:00, avoid the industrial zone",
        "I need to deliver 12 parcels with one van before noon",
        "20 orders, 2 trucks, deadline 17h, do not drive through residential areas",
        "hurricane relief: 28 water deliveries, 4 trucks, avoid flooded streets, by 3:15 pm",
        "15 deliveries, leave at 7 in the morning, finish by 2 in the afternoon, avoid parks",
        "40 orders with 4 trucks, quarter to six in the evening",
        "10 orders, 2 trucks, 5 minutes per stop, by 11",
        "50 orders with 5 trucks, no time limit",
        "avoid the commercial zone. 18 orders, 3 trucks, until 13:45",
        "one truck, 6 stops, leave at 8:30, back at 11:00",
    ],
    "Russian": [
        "30 заказов, 3 грузовика, до 18:00, избегать промышленной зоны",
        "нужно доставить 12 посылок одним фургоном до полудня",
        "20 заказов, 2 грузовика, срок 17 часов, не ехать через жилые кварталы",
        "помощь после урагана: 28 доставок воды, 4 грузовика, избегать затопленных улиц, к 15:15",
        "15 доставок, выезд в 7 утра, закончить к 2 часам дня, обходить парки",
        "40 заказов на 4 грузовика, без пятнадцати шесть вечера",
        "10 заказов, 2 грузовика, по 5 минут на остановку, до 11",
        "50 заказов на 5 грузовиков, без ограничения по времени",
        "обходить коммерческую зону. 18 заказов, 3 грузовика, до 13:45",
        "один грузовик, 6 остановок, выезд в 8:30, вернуться в 11:00",
    ],
    "Spanish": [
        "30 pedidos, 3 camiones, antes de las 18:00, evitar la zona industrial",
        "necesito entregar 12 paquetes con una furgoneta antes del mediodía",
        "20 pedidos, 2 camiones, plazo 17h, sin pasar por zonas residenciales",
        "ayuda tras el huracán: 28 entregas de agua, 4 camiones, evitar calles inundadas, antes de las 3:15 de la tarde",
        "15 entregas, salida a las 7 de la mañana, terminar a las 2 de la tarde, evitar parques",
        "40 pedidos con 4 camiones, a las seis menos cuarto de la tarde",
        "10 pedidos, 2 camiones, 5 minutos por parada, antes de las 11",
        "50 pedidos con 5 camiones, sin hora límite",
        "evitar la zona comercial. 18 pedidos, 3 camiones, hasta las 13:45",
        "un camión, 6 paradas, salir a las 8:30, volver a las 11:00",
    ],
    "French": [
        "30 commandes, 3 camions, avant 18 h, éviter la zone industrielle",
        "je dois livrer 12 colis avec une camionnette avant midi",
        "20 commandes, 2 camions, échéance 17 h, sans passer par les zones résidentielles",
        "aide après l'ouragan : 28 livraisons d'eau, 4 camions, éviter les rues inondées, avant 15 h 15",
        "15 livraisons, départ à 7 h du matin, terminer à 14 h, éviter les parcs",
        "40 commandes avec 4 camions, à six heures moins le quart du soir",
        "10 commandes, 2 camions, 5 minutes par arrêt, avant 11 h",
        "50 commandes avec 5 camions, pas d'heure limite",
        "éviter la zone commerciale. 18 commandes, 3 camions, jusqu'à 13 h 45",
        "un camion, 6 arrêts, départ à 8 h 30, retour à 11 h",
    ],
    "German": [
        "30 Bestellungen, 3 Lkw, bis 18:00, Industriegebiet meiden",
        "ich muss 12 Pakete mit einem Transporter vor Mittag liefern",
        "20 Bestellungen, 2 Lkw, Frist 17 Uhr, nicht durch Wohngebiete fahren",
        "Hilfe nach dem Hurrikan: 28 Wasserlieferungen, 4 Lkw, überflutete Straßen meiden, bis 15:15 Uhr",
        "15 Lieferungen, Start um 7 Uhr morgens, fertig um 14 Uhr, Parks meiden",
        "40 Bestellungen mit 4 Lkw, Viertel vor sechs abends",
        "10 Bestellungen, 2 Lkw, 5 Minuten pro Halt, bis 11 Uhr",
        "50 Bestellungen mit 5 Lkw, keine Zeitvorgabe",
        "Gewerbegebiet meiden. 18 Bestellungen, 3 Lkw, bis 13:45",
        "ein Lkw, 6 Halte, Start 8:30, Rückkehr 11:00",
    ],
    "Portuguese": [
        "30 pedidos, 3 caminhões, até as 18:00, evitar a zona industrial",
        "preciso entregar 12 pacotes com uma van antes do meio-dia",
        "20 pedidos, 2 caminhões, prazo 17h, sem passar por áreas residenciais",
        "ajuda após o furacão: 28 entregas de água, 4 caminhões, evitar ruas alagadas, até as 15:15",
        "15 entregas, saída às 7 da manhã, terminar às 2 da tarde, evitar parques",
        "40 pedidos com 4 caminhões, quinze para as seis da tarde",
        "10 pedidos, 2 caminhões, 5 minutos por parada, até as 11",
        "50 pedidos com 5 caminhões, sem limite de horário",
        "evitar a zona comercial. 18 pedidos, 3 caminhões, até as 13:45",
        "um caminhão, 6 paradas, saída às 8:30, volta às 11:00",
    ],
}


def cases(language: str) -> list[tuple[str, dict]]:
    return list(zip(TEXTS[language], EXPECTED))
