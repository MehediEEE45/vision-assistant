plugins {
    id("vision.android.library")
}

android {
    namespace = "bd.visionassistant.input.asr"
}

dependencies {
    implementation(project(":core"))
    implementation(libs.kotlinx.coroutines.android)
}
