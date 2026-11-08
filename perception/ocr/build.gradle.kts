plugins {
    id("vision.android.library")
}

android {
    namespace = "bd.visionassistant.perception.ocr"
}

dependencies {
    implementation(project(":core"))
    implementation(project(":input:camera"))
    implementation(libs.mlkit.text.recognition)
    implementation(libs.kotlinx.coroutines.android)
}
