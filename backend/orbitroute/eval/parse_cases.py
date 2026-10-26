"""Request-parsing cases: free-form phrasings and the fields a correct parse must contain.

Only listed fields are checked; a field that is omitted here must come back as null / empty.
"""

from __future__ import annotations

# Fields: n_orders, n_vehicles, vehicle_capacity, shift_start, deadline, service_minutes, avoid, objective
CASES: list[tuple[str, dict]] = [
    ("40 orders, 3 trucks, by 18:00, avoid the industrial zone", dict(n_orders=40, n_vehicles=3, deadline="18:00", avoid={"industrial"})),
    ("Deliver 25 packages with 2 vans before 5pm", dict(n_orders=25, n_vehicles=2, deadline="17:00")),
    ("I need twelve deliveries done by noon using one truck", dict(n_orders=12, n_vehicles=1, deadline="12:00")),
    ("50 stops, 4 trucks, start at 07:30, finish by 15:00, no driving through residential areas", dict(n_orders=50, n_vehicles=4, shift_start="07:30", deadline="15:00", avoid={"residential"})),
    ("30 orders, 3 trucks, each stop takes 6 minutes, by 14:00", dict(n_orders=30, n_vehicles=3, service_minutes=6, deadline="14:00")),
    ("20 orders, 2 trucks, each truck holds at most 12 parcels, by 16:00, avoid the commercial zone", dict(n_orders=20, n_vehicles=2, vehicle_capacity=12, deadline="16:00", avoid={"commercial"})),
    ("60 deliveries, 5 vehicles, shortest total distance, by 17:30", dict(n_orders=60, n_vehicles=5, deadline="17:30", objective="min_distance")),
    ("Fastest possible: 18 orders, 2 trucks, by 11:00", dict(n_orders=18, n_vehicles=2, deadline="11:00", objective="min_time")),
    ("avoid both industrial and residential zones, 35 orders, 3 trucks, by 13:00", dict(n_orders=35, n_vehicles=3, deadline="13:00", avoid={"industrial", "residential"})),
    ("10 orders, 1 truck", dict(n_orders=10, n_vehicles=1)),
    ("We have 3 trucks and 45 orders to deliver by 6:30 pm, stay out of the park", dict(n_orders=45, n_vehicles=3, deadline="18:30", avoid={"park_forest"})),
    ("Plan 8 stops for 2 couriers by 10:00", dict(n_orders=8, n_vehicles=2, deadline="10:00")),
    ("28 orders / 4 trucks / deadline 19:00 / keep away from the factories", dict(n_orders=28, n_vehicles=4, deadline="19:00", avoid={"industrial"})),
    ("100 orders, 10 trucks, 08:00-16:00", dict(n_orders=100, n_vehicles=10, shift_start="08:00", deadline="16:00")),
    ("15 orders, 3 trucks, 10 minutes at each stop, avoid residential, by 2 pm", dict(n_orders=15, n_vehicles=3, service_minutes=10, deadline="14:00", avoid={"residential"})),
    ("Route 22 deliveries with 2 trucks departing at 9am and returning by 1pm", dict(n_orders=22, n_vehicles=2, shift_start="09:00", deadline="13:00")),
    ("5 orders, 1 truck, by 9:45", dict(n_orders=5, n_vehicles=1, deadline="09:45")),
    ("33 orders, 3 trucks, by 12:00, but don't go through the industrial zone or the commercial area", dict(n_orders=33, n_vehicles=3, deadline="12:00", avoid={"industrial", "commercial"})),
    ("Two trucks, thirty orders, finish by 17:00", dict(n_orders=30, n_vehicles=2, deadline="17:00")),
    ("14 orders on 2 trucks with capacity 8 each, leave at 6:00, done by 10:30", dict(n_orders=14, n_vehicles=2, vehicle_capacity=8, shift_start="06:00", deadline="10:30")),
]
