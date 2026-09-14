# NZTA Motor Vehicle Register open data — field descriptions

**Source URL:** <https://opendata-nzta.opendata.arcgis.com/pages/mvr-data-field-descriptions>

**Retrieved:** 2026-09-12

The complete field table as published. The page is an ArcGIS Hub app that renders this
table client-side, so the served HTML carries only a truncated copy; the full table was
read from the page item that the page itself loads:
<https://www.arcgis.com/sharing/rest/content/items/de5669aeb6304620b09e79fe84f40b7c/data?f=json>
(`values.layout.sections[1].rows[0].cards[0].component.settings.markdown`).

This project cites it for what the register fields **mean**. It enumerates no permitted
values for any field, which is why the value lists come from the VIRM tables instead.

Transcribed mechanically from the page as served; no wording is edited,
summarised or reordered. Cell line breaks are rendered as `<br>`.

---

## Field descriptions

| Attribute Name | Alias Name | Description | Units | Type |
|---|---|---|---|---|
| ALTERNATIVE_MOTIVE_POWER | Alternative Motive Power | Identifies any alternative or secondary fuel source that powers the vehicle |  | Text (Categorical) |
| BASIC_COLOUR | Basic Colour | The predominant colour of the vehicle |  | Text (Categorical) |
| BODY_TYPE | Body Type | Identifies the vehicle's body shape |  | Text (Categorical) |
| CC_RATING | CC Rating | Total volume in cubic centimetres of the displacement of all cylinders of the vehicle's engine | cc | Integer |
| CHASSIS_7 | Chassis 7 | First 7 characters of the Chassis Number |  | Text (Free) |
| CLASS | Class | Vehicle equipment standard classification |  | Text (Categorical) |
| ENGINE_NUMBER | Engine Number | All characters of the Engine Number |  | Text (Free) |
| FC_COMBINED | Fuel Consumption Combined | The fuel consumption in litres of fuel per 100 kilometres (L/100km) as a weighted combination of the FC_URBAN and FC_EXTRA_URBAN values. | L/100km | Decimal |
| FC_EXTRA_URBAN | Fuel Consumption Extra-Urban | The fuel consumption in litres of fuel per 100 kilometres (L/100km) in an 'extra-urban' cycle (which involves the vehicle accelerating to a high peak speed) of a standard test | L/100km | Decimal |
| FC_URBAN | Fuel Consumption Urban | The fuel consumption in litres of fuel per 100 kilometres (L/100km) in an 'urban' cycle (which represents conditions found in stop?start traffic) of a standard test | L/100km | Decimal |
| FIRST_NZ_REGISTRATION_YEAR | First NZ Registration Year | The year the vehicle was first registered in New Zealand |  | Integer |
| FIRST_NZ_REGISTRATION_MONTH | First NZ Registration Month | The month the vehicle was first registered in New Zealand |  | Integer |
| GROSS_VEHICLE_MASS | Gross Vehicle Mass | The maximum permitted mass of the vehicle in kilograms | kg | Integer |
| HEIGHT | Height | The height of the vehicle measured from the base of the wheel to the top of the vehicle structure | mm | Integer |
| IMPORT_STATUS | Import Status | The status of a vehicle as it arrives into New Zealand |  | Text (Categorical) |
| INDUSTRY_CLASS | Industry Class | The class of industry a vehicle is associated with |  | Text (Categorical) |
| INDUSTRY_MODEL_CODE | Industry Model Code | Non-validated field used by vehicle manufacturers to describe model code on IMPORTED USED VEHICLES particularly from Japan |  | Text (Free) |
| MAKE | Make | The manufacturer of the vehicle |  | Text (Free) |
| MODEL | Model | The model of vehicle as assigned by the manufacturer |  | Text (Free) |
| MOTIVE_POWER | Motive Power | Identifies the primary fuel source that powers the vehicle |  | Text (Categorical) |
| MVMA_MODEL_CODE | MVMA Model Code | Model code is assigned by the manufacturer at the time of VIN allocation to NZ-new vehicles |  | Text (Free) |
| NUMBER_OF_AXLES | Number of Axles | Records the number of axles the vehicle has |  | Integer |
| NUMBER_OF_SEATS | Number of Seats | Records the number of seats in a vehicle |  | Integer |
| NZ_ASSEMBLED | NZ Assembled | Indicates where the vehicle was assembled |  | Text (Categorical) |
| ORIGINAL_COUNTRY | Original Country | The country where the vehicle (or kit) was principally manufactured |  | Text (Categorical) |
| POWER_RATING | Power Rating | The power rating of the vehicle | kW | Integer |
| PREVIOUS_COUNTRY | Previous Country | The country where a used imported vehicle was registered immediately prior to its arrival in New Zealand |  | Text (Categorical) |
| ROAD_TRANSPORT_CODE | Road Transport Code | For vehicles with industry class recorded as "commercial road transport" this shows the type of road transport the vehicle is used for |  | Text (Categorical) |
| SUBMODEL | Sub Model | The sub model of the vehicle as assigned by the manufacturer |  | Text (Free) |
| SYNTHETIC_GREENHOUSE_GAS | Synthetic Greenhouse Gas | The refridgerant used in the air-conditioning system of the vehicle |  | Text (Categorical) |
| TLA | Territorial Authority | The Territorial Authority that the registered owner of the vehicle resides in (one of 67 Districts, Cities, Territories or the Auckland Unitary Authority) |  | Text (Categorical) |
| TRANSMISSION_TYPE | Transmission Type | The gearing system the vehicle has (e.g. automatic or manual). Please note that this is infrequently recorded |  | Text (Categorical) |
| VDAM_WEIGHT | VDAM Weight | The maximum allowable laden weight for the vehicle on the road as determined by the NZ Transport Agency | kg | Integer |
| VEHICLE_TYPE | Vehicle Type | The type of vehicle e.g. motorcycle, passenger car/van, bus etc. Some special purpose and agricultural vehicles have been combined. |  | Text (Categorical) |
| VEHICLE_USAGE | Vehicle Usage | Classification of how a vehicle is used. This field groups several more detailed usage types. |  | Text (Categorical) |
| VEHICLE_YEAR | Vehicle Year | Year of manufacture or model year - if unknown, year of first registration |  | Integer |
| VIN11 | Vin 11 | First 11 characters of the Vehicle Identification Number (VIN) |  | Text (Free) |
| WIDTH | Width | The width of the vehicle | mm | Integer |
