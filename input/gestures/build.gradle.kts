plugins {
    id("vision.android.library")
}

android {
    namespace = "bd.visionassistant.input.gestures"
}

dependencies {
    implementation(project(":core"))
}
