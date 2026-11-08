plugins {
    id("vision.android.library")
}

android {
    namespace = "bd.visionassistant.input.wakeword"
}

dependencies {
    implementation(project(":core"))
}
