<?php
// Only mounted into a disposable CI container; never included in the image.
if (isset($_GET['oom'])) {
    ini_set('memory_limit', '16M');
    register_shutdown_function(function () { echo 'SHUTDOWN_CALLBACK_RAN'; });
    str_repeat('x', 32 * 1024 * 1024);
    exit;
}

session_start();
$_SESSION['counter'] = isset($_SESSION['counter']) ? $_SESSION['counter'] + 1 : 1;
header('Content-Type: application/json');
echo json_encode([
    'version' => PHP_VERSION,
    'sapi' => PHP_SAPI,
    'multipart_limit' => ini_get('max_multipart_body_parts'),
    'session_counter' => $_SESSION['counter'],
    'session_id' => session_id(),
    'form_value' => isset($_POST['smoke']) ? $_POST['smoke'] : null,
]);
