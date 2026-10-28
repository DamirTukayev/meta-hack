"""Harder request phrasings for the parsing evaluation: caps, odd time words, other units, stray detail, no time at all.

Same format as parse_cases.CASES; written by the project author, so they measure robustness to paraphrase, not to the wild.
"""

from __future__ import annotations

HARD_CASES: list[tuple[str, dict]] = [
    ("by noon 3 trucks 18 orders no residential", dict(n_orders=18, n_vehicles=3, deadline="12:00", avoid={"residential"})),
    ("twelve parcels, one van, back by half past four in the afternoon, avoid houses", dict(n_orders=12, n_vehicles=1, deadline="16:30", avoid={"residential"})),
    ("20 orders 2 trucks deadline 17h", dict(n_orders=20, n_vehicles=2, deadline="17:00")),
    ("Need 15 deliveries by tomorrow 10am with 2 couriers", dict(n_orders=15, n_vehicles=2, deadline="10:00")),
    ("plan 25 stops, 5 trucks; leave 7am; be done 2pm; skip the industrial area", dict(n_orders=25, n_vehicles=5, shift_start="07:00", deadline="14:00", avoid={"industrial"})),
    ("40 orders, 4 trucks, quarter to six pm", dict(n_orders=40, n_vehicles=4, deadline="17:45")),
    ("10 orders 2 trucks 5 min per stop by 11", dict(n_orders=10, n_vehicles=2, service_minutes=5, deadline="11:00")),
    ("avoid flood water and parks. 30 orders, 3 trucks, by 5 p.m.", dict(n_orders=30, n_vehicles=3, deadline="17:00", avoid={"flooded", "park_forest"})),
    ("3 trucks, 21 orders, finish by 18:00, drive as little as possible", dict(n_orders=21, n_vehicles=3, deadline="18:00", objective="min_distance")),
    ("i need 9 drops done before lunch (12:30) with a single truck", dict(n_orders=9, n_vehicles=1, deadline="12:30")),
    ("BY 14:00!!! 16 ORDERS / 2 TRUCKS / AVOID INDUSTRIAL", dict(n_orders=16, n_vehicles=2, deadline="14:00", avoid={"industrial"})),
    ("deliver 35 orders using 4 trucks; each truck can take 10; deadline 15:30; stay away from commercial streets", dict(n_orders=35, n_vehicles=4, vehicle_capacity=10, deadline="15:30", avoid={"commercial"})),
    ("50 orders with 5 trucks, nothing about time", dict(n_orders=50, n_vehicles=5)),
    ("orders: 12, trucks: 3, deadline: 13:45, avoid: residential, industrial", dict(n_orders=12, n_vehicles=3, deadline="13:45", avoid={"residential", "industrial"})),
    ("6 stops 1 truck leave 8:30 return 11:00", dict(n_orders=6, n_vehicles=1, shift_start="08:30", deadline="11:00")),
    ("avoid the residential area (houses) 22 orders 3 trucks by 10 pm", dict(n_orders=22, n_vehicles=3, deadline="22:00", avoid={"residential"})),
    ("Hurricane relief: 28 water deliveries, 4 trucks, avoid roads under water, by 3:15 pm", dict(n_orders=28, n_vehicles=4, deadline="15:15", avoid={"flooded"})),
    ("30 orders on 3 trucks, 6 minutes per stop and by 16:00 avoiding parks", dict(n_orders=30, n_vehicles=3, service_minutes=6, deadline="16:00", avoid={"park_forest"})),
    ("one truck, 5 orders", dict(n_orders=5, n_vehicles=1)),
    ("Please plan 24 deliveries for 3 vans, they should be back no later than 6:45 pm and must not enter the flooded areas or the factories", dict(n_orders=24, n_vehicles=3, deadline="18:45", avoid={"flooded", "industrial"})),
]
