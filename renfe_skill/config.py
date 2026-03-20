"""RENFE GTFS configuration and constants."""

GTFS_STATIC_URL = "https://ssl.renfe.com/ftransit/Fichero_CER_FOMENTO/fomento_transit.zip"
GTFS_RT_VEHICLE_POSITIONS = "https://gtfsrt.renfe.com/vehicle_positions.pb"
GTFS_RT_TRIP_UPDATES = "https://gtfsrt.renfe.com/trip_updates.pb"
GTFS_RT_ALERTS = "https://gtfsrt.renfe.com/alerts.pb"

# Long distance / Media Distancia feeds (no alerts feed available)
GTFS_RT_VEHICLE_POSITIONS_LD = "https://gtfsrt.renfe.com/vehicle_positions_LD.pb"
GTFS_RT_TRIP_UPDATES_LD = "https://gtfsrt.renfe.com/trip_updates_LD.pb"

# Cercanías network prefix -> city/region name
NUCLEUS_NAMES = {
    "10": "Madrid",
    "20": "Asturias",
    "30": "Sevilla",
    "31": "Cádiz",
    "32": "Málaga",
    "40": "Valencia",
    "41": "Murcia/Alicante",
    "51": "Rodalies Catalunya",
    "60": "Bilbao",
    "61": "San Sebastián",
    "62": "Santander",
    "70": "Zaragoza",
    "90": "Cercedilla/Cotos",
}
