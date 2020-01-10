package Demo.Main.State;

import Demo.Main.GamePanel;
import Demo.Main.Resources;
//import Demo.Main.GamePanel;

import java.awt.*;
import java.awt.event.KeyEvent;

/**
 * Created by jassiboy on 2/26/2017.
 */
public class MenuState extends State {

    private int selectedOption = 0;

    @Override
    public void update() {}

    @Override
    public void render(Graphics g) {
        g.drawImage(Resources.welcomeImage, 0, 0, null);

        if(selectedOption == 0) {
            g.drawImage(Resources.arrowImage, 445, 295, null);
        } else {
            g.drawImage(Resources.arrowImage, 445, 345, null);
        }
    }

    @Override
    public void onKeyPressed(int pressedKeyCode) {

        if(pressedKeyCode == KeyEvent.VK_UP) {
            selectedOption = 0;
        } else if(pressedKeyCode == KeyEvent.VK_DOWN) {
            selectedOption = 1;
        } else if(pressedKeyCode == KeyEvent.VK_ENTER) {
            Resources.flapAudio.play();
            if(selectedOption ==0 ) {
                GamePanel.currentState = new Stage1State();
            } else {
                // exit the game
            }
        }
    }
}
