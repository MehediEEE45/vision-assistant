plugins {
    id("vision.android.library")
}

android {
    namespace = "bd.visionassistant.input.location"
}

dependencies {
    implementation(project(":core"))
    implementation(libs.play.services.location)
}
