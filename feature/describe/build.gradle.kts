plugins {
    id("vision.android.library")
}

android {
    namespace = "bd.visionassistant.feature.describe"
}

dependencies {
    implementation(project(":core"))
    implementation(project(":spine:output-arbiter"))
    implementation(project(":perception:objects"))
}
