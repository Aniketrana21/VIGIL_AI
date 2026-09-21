plugins {
    id("com.android.application") version "8.3.0" apply false
    id("org.jetbrains.kotlin.android") version "1.9.22" apply false
}

allprojects {
    layout.buildDirectory.set(file("C:/Users/ANIKET/.gradle_builds/vigilai/${project.name}"))
}

