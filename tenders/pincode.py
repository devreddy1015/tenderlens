"""Indian PIN code -> state, using India Post's postal-circle prefixes.

The first digits of a PIN identify the postal circle. Circles mostly match states;
the exceptions (e.g. Goa inside Maharashtra's 40x, Uttarakhand inside UP's 24x-26x)
are listed as 3- and 4-digit overrides, which are checked first. This is accurate at
the state level for the vast majority of PINs, not a full post-office directory.
"""

_THREE_DIGIT = {
    "160": "Chandigarh",
    "194": "Ladakh",
    "244": "Uttarakhand",  # 2447xx (Kashipur, Ramnagar)
    "246": "Uttarakhand",
    "247": "Uttarakhand",  # 2476xx-2477xx Haridwar/Roorkee; 247001 Saharanpur is UP (see below)
    "248": "Uttarakhand",
    "249": "Uttarakhand",
    "262": "Uttarakhand",  # 2625xx-2626xx Pithoragarh/Champawat; 2620-2624 are UP (see below)
    "263": "Uttarakhand",
    "403": "Goa",
    "605": "Puducherry",
    "682": "Kerala",
    "737": "Sikkim",
    "744": "Andaman and Nicobar Islands",
    "790": "Arunachal Pradesh",
    "791": "Arunachal Pradesh",
    "792": "Arunachal Pradesh",
    "793": "Meghalaya",
    "794": "Meghalaya",
    "795": "Manipur",
    "796": "Mizoram",
    "797": "Nagaland",
    "798": "Nagaland",
    "799": "Tripura",
    "814": "Jharkhand",
    "815": "Jharkhand",
    "816": "Jharkhand",
    "825": "Jharkhand",
    "826": "Jharkhand",
    "827": "Jharkhand",
    "828": "Jharkhand",
    "829": "Jharkhand",
    "831": "Jharkhand",
    "832": "Jharkhand",
    "833": "Jharkhand",
    "834": "Jharkhand",
    "835": "Jharkhand",
}

# Longer prefixes that override the 3-digit table.
_LONG_PREFIX = {
    "2470": "Uttar Pradesh",  # Saharanpur 2470xx
    "2471": "Uttar Pradesh",
    "2472": "Uttar Pradesh",
    "2473": "Uttar Pradesh",
    "2474": "Uttar Pradesh",
    "2620": "Uttar Pradesh",
    "2621": "Uttar Pradesh",
    "2622": "Uttar Pradesh",
    "2623": "Uttar Pradesh",
    "2624": "Uttar Pradesh",
    "2440": "Uttar Pradesh",
    "2441": "Uttar Pradesh",
    "2442": "Uttar Pradesh",
    "2443": "Uttar Pradesh",
    "2444": "Uttar Pradesh",
    "2445": "Uttar Pradesh",
    "2446": "Uttar Pradesh",
    "2448": "Uttar Pradesh",
    "2449": "Uttar Pradesh",
    "3962": "Dadra and Nagar Haveli and Daman and Diu",
    "6825": "Lakshadweep",
    "6098": "Puducherry",  # Karaikal
    "5333": "Puducherry",  # Yanam
    "6731": "Puducherry",  # Mahe
}

_TWO_DIGIT = {
    "11": "Delhi",
    "12": "Haryana",
    "13": "Haryana",
    "14": "Punjab",
    "15": "Punjab",
    "16": "Punjab",
    "17": "Himachal Pradesh",
    "18": "Jammu and Kashmir",
    "19": "Jammu and Kashmir",
    "20": "Uttar Pradesh",
    "21": "Uttar Pradesh",
    "22": "Uttar Pradesh",
    "23": "Uttar Pradesh",
    "24": "Uttar Pradesh",
    "25": "Uttar Pradesh",
    "26": "Uttar Pradesh",
    "27": "Uttar Pradesh",
    "28": "Uttar Pradesh",
    "30": "Rajasthan",
    "31": "Rajasthan",
    "32": "Rajasthan",
    "33": "Rajasthan",
    "34": "Rajasthan",
    "36": "Gujarat",
    "37": "Gujarat",
    "38": "Gujarat",
    "39": "Gujarat",
    "40": "Maharashtra",
    "41": "Maharashtra",
    "42": "Maharashtra",
    "43": "Maharashtra",
    "44": "Maharashtra",
    "45": "Madhya Pradesh",
    "46": "Madhya Pradesh",
    "47": "Madhya Pradesh",
    "48": "Madhya Pradesh",
    "49": "Chhattisgarh",
    "50": "Telangana",
    "51": "Andhra Pradesh",
    "52": "Andhra Pradesh",
    "53": "Andhra Pradesh",
    "56": "Karnataka",
    "57": "Karnataka",
    "58": "Karnataka",
    "59": "Karnataka",
    "60": "Tamil Nadu",
    "61": "Tamil Nadu",
    "62": "Tamil Nadu",
    "63": "Tamil Nadu",
    "64": "Tamil Nadu",
    "67": "Kerala",
    "68": "Kerala",
    "69": "Kerala",
    "70": "West Bengal",
    "71": "West Bengal",
    "72": "West Bengal",
    "73": "West Bengal",
    "74": "West Bengal",
    "75": "Odisha",
    "76": "Odisha",
    "77": "Odisha",
    "78": "Assam",
    "80": "Bihar",
    "81": "Bihar",
    "82": "Bihar",
    "83": "Bihar",
    "84": "Bihar",
    "85": "Bihar",
}


def state_from_pincode(pincode: str | None) -> str:
    """Return the state name, or "" when the PIN is missing or not a valid 6-digit PIN."""
    if not pincode:
        return ""
    pin = pincode.strip()
    if len(pin) != 6 or not pin.isdigit() or pin[0] == "0":
        return ""
    for table, n in ((_LONG_PREFIX, 4), (_THREE_DIGIT, 3), (_TWO_DIGIT, 2)):
        state = table.get(pin[:n])
        if state:
            return state
    return ""


# Every state / union territory name this module can return.
ALL_STATES = (
    frozenset(_TWO_DIGIT.values())
    | frozenset(_THREE_DIGIT.values())
    | frozenset(_LONG_PREFIX.values())
)
