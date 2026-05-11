#[derive(Debug, Default, Clone)]
pub struct RetryConfig {
    pub max_attempts: i32,
    pub wait_seconds: f32,
    pub on_exceptions: Vec<String>,
    pub on_status_codes: Vec<i32>,
}

#[derive(Debug, Default, Clone)]
pub struct RedactConfig {
    pub full: i32,
    pub partial: f32,
    pub hashed: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct PolicySpec {
    pub retry: RetryConfig,
    pub redact: RedactConfig,
    pub name: String,
}


// Ploicy Driven testing for eBPF programs