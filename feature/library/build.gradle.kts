plugins {
    id("vision.android.library")
}

android {
    namespace = "bd.visionassistant.feature.library"
}

dependencies {
    implementation(project(":core"))
    implementation(project(":spine:output-arbiter"))
    implementation(libs.androidx.room.runtime)
    implementation(libs.androidx.room.ktx)
}
