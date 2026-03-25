"""Shared NFHS level constants and normalization helpers."""

SUPPORTED_LEVELS = {
    "Varsity",
    "Junior Varsity",
    "Sophomore",
    "Freshman",
    "Middle School",
}

DEFAULT_SELECTED_LEVELS = [
    "Varsity",
]

LEVEL_NORMALIZATION = {
    "Varsity": "Varsity",
    "varsity": "Varsity",
    "Junior Varsity": "Junior Varsity",
    "junior varsity": "Junior Varsity",
    "JV": "Junior Varsity",
    "jv": "Junior Varsity",
    "Sophomore": "Sophomore",
    "sophomore": "Sophomore",
    "Freshman": "Freshman",
    "freshman": "Freshman",
    "Middle School": "Middle School",
    "middle school": "Middle School",
    "MiddleSchool": "Middle School",
    "middleschool": "Middle School",
    "MS": "Middle School",
    "ms": "Middle School",
}

LEVEL_QUERY_VALUE_BY_LEVEL = {
    "Varsity": "varsity",
    "Junior Varsity": "junior varsity",
    "Sophomore": "sophomore",
    "Freshman": "freshman",
    "Middle School": "middle school",
}
