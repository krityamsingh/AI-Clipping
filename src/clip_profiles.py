"""Supported video categories and actual renderable editing styles.

Categories select *which events to prioritize*. Editing styles control the
existing renderer's framing, captions and restrained grading. These are not
promises of semantic recognition or unsupported animation effects.
"""
from dataclasses import dataclass

PROFILES = (
    "general", "livestream", "gaming", "esports", "sports", "podcast",
    "interview", "talking_head", "reaction", "comedy", "vlog", "travel",
    "tutorial", "education", "technology", "product_demo", "review",
    "documentary", "news", "music", "dance", "cooking", "trailer"
)

# Weights apply to *relative evidence*, not estimates of virality.
SIGNAL_WEIGHTS = {
    "livestream": (0.38, 0.32, 0.30),
    "gaming": (0.50, 0.35, 0.15),
    "esports": (0.55, 0.25, 0.20),
    "sports": (0.58, 0.33, 0.09),
    "reaction": (0.28, 0.45, 0.27),
    "comedy": (0.20, 0.52, 0.28),
    "music": (0.40, 0.55, 0.05),
    "dance": (0.60, 0.38, 0.02),
    "trailer": (0.48, 0.48, 0.04),
    "vlog": (0.45, 0.45, 0.10),
    "travel": (0.58, 0.37, 0.05),
    "cooking": (0.49, 0.45, 0.06),
    "general": (0.40, 0.45, 0.15),
}

DEFAULT_STYLES = {
    "livestream": "energetic", "gaming": "gaming", "esports": "gaming",
    "sports": "energetic", "podcast": "podcast", "interview": "podcast",
    "talking_head": "clean", "tutorial": "tutorial",
    "education": "tutorial", "technology": "tutorial",
    "product_demo": "clean", "review": "clean",
    "news": "documentary", "documentary": "documentary",
    "trailer": "cinematic", "music": "cinematic", "dance": "energetic",
    "reaction": "energetic", "comedy": "energetic",
    "vlog": "clean", "travel": "cinematic", "cooking": "clean",
    "general": "clean",
}

# Safe explicit values fed to CaptionGenerator.
EDIT_STYLES = {
    "clean": {"font_size": 47, "highlight_color": "&H0000FFFF",
              "outline_width": 3.0, "margin_v": 180, "max_words_per_group": 5,
              "layout": "blur_fill", "color_correction": False},
    "energetic": {"font_size": 55, "highlight_color": "&H0000FFFF",
                  "outline_width": 4.0, "margin_v": 210, "max_words_per_group": 3,
                  "layout": "blur_fill", "color_correction": True},
    "gaming": {"font_size": 50, "highlight_color": "&H0000D7FF",
               "outline_width": 4.0, "margin_v": 220, "max_words_per_group": 3,
               "layout": "fit_pad", "color_correction": False},
    "podcast": {"font_size": 45, "highlight_color": "&H00E0FFFF",
                "outline_width": 3.5, "margin_v": 200, "max_words_per_group": 5,
                "layout": "blur_fill", "color_correction": False},
    "tutorial": {"font_size": 42, "highlight_color": "&H00CCFFCC",
                 "outline_width": 3.0, "margin_v": 140, "max_words_per_group": 5,
                 "layout": "fit_pad", "color_correction": False},
    "cinematic": {"font_size": 43, "highlight_color": "&H00FFFFFF",
                  "outline_width": 2.5, "margin_v": 150, "max_words_per_group": 5,
                  "layout": "fit_pad", "color_correction": False},
    "documentary": {"font_size": 42, "highlight_color": "&H00FFFFFF",
                    "outline_width": 3.0, "margin_v": 160, "max_words_per_group": 6,
                    "layout": "fit_pad", "color_correction": False},
    "minimal": {"font_size": 40, "highlight_color": "&H00FFFFFF",
                "outline_width": 2.0, "margin_v": 140, "max_words_per_group": 6,
                "layout": "fit_pad", "color_correction": False},
}

def get_style(style=None, profile="general"):
    if profile not in PROFILES:
        raise ValueError("Unsupported profile: " + str(profile))
    name = style or DEFAULT_STYLES[profile]
    if name not in EDIT_STYLES:
        raise ValueError("Unsupported editing style: " + str(name))
    return name, dict(EDIT_STYLES[name])
