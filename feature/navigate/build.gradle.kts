plugins {
    id("vision.android.library")
}

android {
    namespace = "bd.visionassistant.feature.navigate"
}

dependencies {
    implementation(project(":core"))
    implementation(project(":spine:output-arbiter"))
    implementation(project(":spine:session-state"))
    implementation(project(":input:location"))
}
