pluginManagement {
    repositories {
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "VisionAssistant"

include(":app")

// --- core -------------------------------------------------------------------
include(":core")
include(":protocol")

// --- spine ------------------------------------------------------------------
// Nothing above this layer may speak or vibrate on its own. See docs/architecture.md.
include(":spine:output-arbiter")
include(":spine:intent-router")
include(":spine:session-state")
include(":spine:safety-policy")

// --- input ------------------------------------------------------------------
include(":input:wakeword")
include(":input:asr")
include(":input:camera")
include(":input:location")
include(":input:ble-link")
include(":input:gestures")

// --- perception -------------------------------------------------------------
include(":perception:obstacle-fusion")
include(":perception:fall-detect")
include(":perception:objects")
include(":perception:ocr")

// --- output -----------------------------------------------------------------
include(":output:tts")
include(":output:earcons")
include(":output:haptics")
include(":output:messaging")

// --- features ---------------------------------------------------------------
include(":feature:navigate")
include(":feature:reader")
include(":feature:library")
include(":feature:describe")
include(":feature:sos")
include(":feature:settings-voice")
