plugins {
    id("vision.android.library")
}

android {
    namespace = "bd.visionassistant.output.tts"
}

dependencies {
    implementation(project(":core"))
    implementation(project(":spine:output-arbiter"))
    implementation(libs.kotlinx.coroutines.android)
}
