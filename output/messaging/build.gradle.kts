plugins {
    id("vision.android.library")
}

android {
    namespace = "bd.visionassistant.output.messaging"
}

dependencies {
    implementation(project(":core"))
}
