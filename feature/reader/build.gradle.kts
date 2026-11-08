plugins {
    id("vision.android.library")
}

android {
    namespace = "bd.visionassistant.feature.reader"
}

dependencies {
    implementation(project(":core"))
    implementation(project(":spine:output-arbiter"))
    implementation(project(":spine:session-state"))
    implementation(project(":perception:ocr"))
    implementation(libs.kotlinx.coroutines.core)

    testImplementation(libs.kotlinx.coroutines.test)
}
