plugins {
    id("vision.android.library")
}

android {
    namespace = "bd.visionassistant.input.ble"
}

dependencies {
    implementation(project(":core"))
    api(project(":protocol"))
    implementation(libs.kotlinx.coroutines.android)
}
