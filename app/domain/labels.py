"""Display labels and deterministic fallback sentences in English and Hindi.

Templates use the same {{key}} placeholder syntax as the narrator. A leading `{{.key}}` is
rewritten to the action's own prefix (for example `{{a1.key}}`) when rendered, so the same
text works for every action.
"""

from __future__ import annotations

from typing import Final

from app.domain.models import ActionKind, HomeSource, Language, TravelMode

MODE_LABELS: Final[dict[Language, dict[str, str]]] = {
    Language.EN: {
        TravelMode.WALK: "walking",
        TravelMode.CYCLE: "cycling",
        TravelMode.TWO_WHEELER: "two-wheeler",
        TravelMode.AUTO_RICKSHAW: "auto-rickshaw",
        TravelMode.CAR: "car",
        TravelMode.BUS: "bus",
        TravelMode.METRO: "metro",
    },
    Language.HI: {
        TravelMode.WALK: "पैदल",
        TravelMode.CYCLE: "साइकिल",
        TravelMode.TWO_WHEELER: "दोपहिया",
        TravelMode.AUTO_RICKSHAW: "ऑटो-रिक्शा",
        TravelMode.CAR: "कार",
        TravelMode.BUS: "बस",
        TravelMode.METRO: "मेट्रो",
    },
}

CATEGORY_LABELS: Final[dict[Language, dict[str, str]]] = {
    Language.EN: {
        "good": "Good",
        "satisfactory": "Satisfactory",
        "moderate": "Moderate",
        "poor": "Poor",
        "very_poor": "Very poor",
        "severe": "Severe",
    },
    Language.HI: {
        "good": "अच्छा",
        "satisfactory": "संतोषजनक",
        "moderate": "मध्यम",
        "poor": "खराब",
        "very_poor": "बहुत खराब",
        "severe": "गंभीर",
    },
}

SOURCE_LABELS: Final[dict[Language, dict[str, str]]] = {
    Language.EN: {
        HomeSource.INCENSE: "incense",
        HomeSource.MOSQUITO_COIL: "mosquito coil",
        HomeSource.FRYING: "deep frying",
        HomeSource.DIYA: "oil lamp (diya)",
        HomeSource.WOOD_COOKING: "wood cooking",
        HomeSource.WASTE_BURNING: "waste burning",
        HomeSource.COAL_HEATING: "coal heating",
        HomeSource.FIRECRACKERS: "firecrackers",
    },
    Language.HI: {
        HomeSource.INCENSE: "अगरबत्ती",
        HomeSource.MOSQUITO_COIL: "मच्छर कॉइल",
        HomeSource.FRYING: "तलना",
        HomeSource.DIYA: "दीया",
        HomeSource.WOOD_COOKING: "लकड़ी पर खाना पकाना",
        HomeSource.WASTE_BURNING: "कचरा जलाना",
        HomeSource.COAL_HEATING: "कोयले की अंगीठी",
        HomeSource.FIRECRACKERS: "पटाखे",
    },
}

DAYPART_PREFIX: Final[dict[Language, tuple[str, str, str, str]]] = {
    Language.EN: ("", "", "", ""),
    Language.HI: ("सुबह ", "दोपहर ", "शाम ", "रात "),
}

# Fallback sentence for each action kind. Keys referenced here are produced by the planner.
ACTION_TEMPLATES: Final[dict[Language, dict[ActionKind, str]]] = {
    Language.EN: {
        ActionKind.SHIFT_ACTIVITY: (
            "Move {{.subject}} ({{.members}}) from {{.old_start}} to {{.new_start}}. Forecast "
            "{{pm}} drops from {{.pm_before}} to {{.pm_after}} µg/m³ and the air is less "
            "stagnant. The inhaled dose falls about {{.dose_cut_pct}}%."
        ),
        ActionKind.MASK: (
            "Wear a well-fitted {{n95}} for {{.subject}} ({{.members}}). It cuts the inhaled dose "
            "by about {{.dose_cut_pct}}%, about {{.avoided_ug}} µg avoided today."
        ),
        ActionKind.MODE_SWITCH: (
            "Switch {{.subject}} ({{.members}}) from {{.mode_old}} to {{.mode_new}}. Inhaled "
            "dose changes by {{.dose_cut_pct}}% and you avoid {{.co2}} kg of CO₂."
        ),
        ActionKind.DEPARTURE_SHIFT: (
            "Leave for {{.subject}} at {{.new_start}} instead of {{.old_start}}. The air on the "
            "road is cleaner and the dose drops about {{.dose_cut_pct}}%."
        ),
        ActionKind.RECIRCULATION: (
            "Close the windows and use recirculation on {{.subject}} ({{.members}}). The inhaled "
            "dose drops about {{.dose_cut_pct}}%."
        ),
        ActionKind.PURIFIER: (
            "A purifier rated {{.cadr}} m³/h in {{.subject}} brings indoor {{pm}} from "
            "{{.indoor_before}} to {{.indoor_after}} µg/m³, cutting the dose about "
            "{{.dose_cut_pct}}%."
        ),
        ActionKind.CR_BOX: (
            "A Corsi-Rosenthal box (box fan with four filters) in {{.subject}} brings indoor "
            "{{pm}} from {{.indoor_before}} to {{.indoor_after}} µg/m³, cutting the dose about "
            "{{.dose_cut_pct}}%."
        ),
        ActionKind.SEAL_GAPS: (
            "Sealing window gaps in {{.subject}} brings indoor {{pm}} from {{.indoor_before}} "
            "to {{.indoor_after}} µg/m³, cutting the dose about {{.dose_cut_pct}}%."
        ),
        ActionKind.SKIP_SOURCE: (
            "Skipping {{.subject}} keeps about {{.indoor_increase}} µg/m³ of {{pm}} out of the "
            "{{.room}} while it would be in use."
        ),
        ActionKind.STOP_BURNING: (
            "Skip {{.subject}}: it puts about {{.pm_g}} g of {{pm}} and {{.co2}} kg of CO₂ into "
            "your neighbourhood's air today."
        ),
    },
    Language.HI: {
        ActionKind.SHIFT_ACTIVITY: (
            "{{.members}} के लिए {{.subject}} को {{.old_start}} से {{.new_start}} पर ले जाएँ। "
            "पूर्वानुमानित {{pm}} {{.pm_before}} से घटकर {{.pm_after}} µg/m³ रह जाएगा और हवा "
            "कम ठहरी हुई होगी। साँस में जाने वाली मात्रा लगभग {{.dose_cut_pct}}% घटेगी।"
        ),
        ActionKind.MASK: (
            "{{.subject}} ({{.members}}) के लिए सही बैठने वाला {{n95}} मास्क पहनें। इससे साँस में "
            "जाने वाली मात्रा लगभग {{.dose_cut_pct}}% घटती है, आज लगभग {{.avoided_ug}} µg बचते हैं।"
        ),
        ActionKind.MODE_SWITCH: (
            "{{.subject}} ({{.members}}) के लिए {{.mode_old}} की जगह {{.mode_new}} चुनें। "
            "साँस में जाने वाली मात्रा {{.dose_cut_pct}}% बदलती है और {{.co2}} किग्रा CO₂ बचती है।"
        ),
        ActionKind.DEPARTURE_SHIFT: (
            "{{.subject}} के लिए {{.old_start}} की जगह {{.new_start}} पर निकलें। सड़क की हवा "
            "साफ़ होगी और मात्रा लगभग {{.dose_cut_pct}}% घटेगी।"
        ),
        ActionKind.RECIRCULATION: (
            "{{.subject}} ({{.members}}) में खिड़कियाँ बंद रखें और रीसर्कुलेशन चलाएँ। "
            "मात्रा लगभग {{.dose_cut_pct}}% घटेगी।"
        ),
        ActionKind.PURIFIER: (
            "{{.subject}} में {{.cadr}} m³/h का प्यूरीफ़ायर घर के अंदर का {{pm}} {{.indoor_before}} "
            "से घटाकर {{.indoor_after}} µg/m³ कर देता है, यानी मात्रा लगभग {{.dose_cut_pct}}% कम।"
        ),
        ActionKind.CR_BOX: (
            "{{.subject}} में कॉर्सी-रोज़ेंथल बॉक्स (बॉक्स फ़ैन और चार फ़िल्टर) अंदर का {{pm}} "
            "{{.indoor_before}} से घटाकर {{.indoor_after}} µg/m³ कर देता है, यानी मात्रा लगभग "
            "{{.dose_cut_pct}}% कम।"
        ),
        ActionKind.SEAL_GAPS: (
            "{{.subject}} की खिड़कियों की दरारें बंद करने से अंदर का {{pm}} {{.indoor_before}} से "
            "घटकर {{.indoor_after}} µg/m³ हो जाता है, यानी मात्रा लगभग {{.dose_cut_pct}}% कम।"
        ),
        ActionKind.SKIP_SOURCE: (
            "{{.subject}} न करने से इस्तेमाल के दौरान {{.room}} में लगभग {{.indoor_increase}} "
            "µg/m³ {{pm}} कम रहता है।"
        ),
        ActionKind.STOP_BURNING: (
            "{{.subject}} से बचें: इससे आज आपके मोहल्ले की हवा में लगभग {{.pm_g}} ग्राम {{pm}} और "
            "{{.co2}} किग्रा CO₂ जुड़ती है।"
        ),
    },
}

SUMMARY_TEMPLATES: Final[dict[Language, str]] = {
    Language.EN: (
        "Air is worst around {{peak_time}} at {{peak_pm25}} µg/m³ ({{peak_category}}) and "
        "cleanest around {{best_time}} at {{best_pm25}} µg/m³. Following this plan cuts the "
        "household's inhaled dose by about {{household_cut_pct}}%."
    ),
    Language.HI: (
        "हवा {{peak_time}} के आसपास सबसे ख़राब ({{peak_pm25}} µg/m³, {{peak_category}}) और "
        "{{best_time}} के आसपास सबसे साफ़ ({{best_pm25}} µg/m³) रहेगी। यह योजना अपनाने से "
        "परिवार की साँस में जाने वाली मात्रा लगभग {{household_cut_pct}}% घटती है।"
    ),
}
